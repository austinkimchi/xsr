/*
 * Userspace control process for SK_SKB/SOCKMAP prompt routing.
 *
 * This process listens for plaintext frontend TCP connections, opens one
 * backend TCP connection per route for each accepted client, inserts all
 * sockets into a SOCKMAP, and populates the BPF routing/decision maps before
 * attaching programs.
 */

#include <arpa/inet.h>
#include <bpf/bpf.h>
#include <bpf/libbpf.h>
#include <errno.h>
#include <linux/bpf.h>
#include <linux/if_link.h>
#include <net/if.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <unistd.h>

#include "bpf/xdp_keyword_modules.generated.h"
#if XDP_KEYWORD_ENABLE_NGRAM
#include "bpf/xdp_ngram_classifier.bpf.h"
#include "bpf/xdp_jaccard_policy.generated.h"
#endif
#if XDP_KEYWORD_ENABLE_BM25
#include "bpf/xdp_bm25_classifier.bpf.h"
#include "bpf/xdp_bm25_policy.generated.h"
#endif
#include "bpf/xdp_signals.bpf.h"
#include "xdp_router.h"

#define BPF_OBJECT_FILE "sk_router.bpf.o"
#define XDP_BPF_OBJECT_FILE "xdp_router.bpf.o"
#define XDP_PROGRAM_NAME "xdp_router"
#define FRONTEND_PORT 18081
#define BACKEND_HOST "127.0.0.1"
#define BACKEND_CODING_PORT 18391
#define BACKEND_MATH_PORT 18392
#define BACKEND_OTHERS_PORT 18393
#define BACKEND_QA_PORT 18394
#define BACKEND_WRITING_PORT 18395

#define SK_ROUTER_FLAG_BACKEND 1
#define SK_MODEL_CODING 1
#define SK_MODEL_MATH 2
#define SK_MODEL_OTHERS 3
#define SK_MODEL_QA 4
#define SK_MODEL_WRITING 5
#define MAX_SOCK_SLOTS 16384
#define MAX_HTTP_MESSAGE (256 * 1024)

struct xdp_decision_rule {
  __u64 require_any;
  __u64 require_all;
  __u64 reject_any;
  __u32 model_id;
  __u32 enabled;
};

struct sk_route_entry {
  __u32 client_slot;
  __u32 coding_slot;
  __u32 math_slot;
  __u32 others_slot;
  __u32 qa_slot;
  __u32 writing_slot;
  __u32 flags;
};

static volatile sig_atomic_t running = 1;

struct xdp_classifier_runtime {
  struct bpf_object *obj;
  struct bpf_link *link;
  int decisions_fd;
};

static void bump_memlock_rlimit(void);

static void handle_signal(int sig) {
  (void)sig;
  running = 0;
}

static int install_signal_handlers(void) {
  struct sigaction action = {
      .sa_handler = handle_signal,
  };

  sigemptyset(&action.sa_mask);
  /* Do not request SA_RESTART: accept() must return EINTR so the main loop
   * can observe running == 0 immediately. */
  if (sigaction(SIGINT, &action, NULL) != 0)
    return -1;
  return sigaction(SIGTERM, &action, NULL);
}

static int set_reuse_and_nodelay(int fd) {
  int one = 1;

  setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
  return setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
}

static int get_socket_cookie(int fd, __u64 *cookie) {
  socklen_t len = sizeof(*cookie);

  if (getsockopt(fd, SOL_SOCKET, SO_COOKIE, cookie, &len) != 0)
    return -1;
  return 0;
}

static int connect_backend(int port) {
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  struct sockaddr_in addr;

  if (fd < 0)
    return -1;

  set_reuse_and_nodelay(fd);
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_port = htons(port);
  if (inet_pton(AF_INET, BACKEND_HOST, &addr.sin_addr) != 1) {
    close(fd);
    errno = EINVAL;
    return -1;
  }

  if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
    close(fd);
    return -1;
  }

  return fd;
}

static int create_listener(void) {
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  struct sockaddr_in addr;

  if (fd < 0)
    return -1;

  set_reuse_and_nodelay(fd);
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons(FRONTEND_PORT);

  if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0 ||
      listen(fd, 1024) != 0) {
    close(fd);
    return -1;
  }

  return fd;
}

static int update_sock_map(int sock_map_fd, __u32 slot, int sock_fd) {
  return bpf_map_update_elem(sock_map_fd, &slot, &sock_fd, BPF_ANY);
}

static int update_route(int routes_fd, int sock_fd,
                        const struct sk_route_entry *entry) {
  __u64 cookie = 0;

  if (get_socket_cookie(sock_fd, &cookie) != 0)
    return -1;

  return bpf_map_update_elem(routes_fd, &cookie, entry, BPF_ANY);
}

static int populate_decision_rules(int rules_fd) {
  struct xdp_decision_rule rules[5] = {
      {.require_any = XDP_SIGNAL_DOMAIN_CODING,
       .model_id = SK_MODEL_CODING,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_MATH,
       .model_id = SK_MODEL_MATH,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_OTHERS,
       .model_id = SK_MODEL_OTHERS,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_QA,
       .model_id = SK_MODEL_QA,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_WRITING,
       .model_id = SK_MODEL_WRITING,
       .enabled = 1},
  };

  for (__u32 i = 0; i < 5; i++) {
    if (bpf_map_update_elem(rules_fd, &i, &rules[i], BPF_ANY) != 0)
      return -1;
  }

  for (__u32 i = 0; i < 5; i++) {
    struct xdp_decision_rule check = {};

    if (bpf_map_lookup_elem(rules_fd, &i, &check) != 0 || !check.enabled ||
        check.model_id != rules[i].model_id ||
        check.require_any != rules[i].require_any) {
      errno = EINVAL;
      return -1;
    }
  }

  return 0;
}

#if XDP_KEYWORD_ENABLE_NGRAM
static int populate_jaccard_policy(struct bpf_object *obj) {
  int config_fd = bpf_object__find_map_fd_by_name(obj, "xdp_jaccard_config");
  int rules_fd = bpf_object__find_map_fd_by_name(obj, "xdp_jaccard_rules");
  int keywords_fd =
      bpf_object__find_map_fd_by_name(obj, "xdp_jaccard_keywords");
  int grams_fd = bpf_object__find_map_fd_by_name(obj, "xdp_jaccard_gram_masks");
  int casefolds_fd =
      bpf_object__find_map_fd_by_name(obj, "xdp_jaccard_casefolds");
  __u32 key = 0;

  if (config_fd < 0 || rules_fd < 0 || keywords_fd < 0 || grams_fd < 0 ||
      casefolds_fd < 0)
    return -1;
  if (bpf_map_update_elem(config_fd, &key, &xdp_jaccard_generated_config,
                          BPF_ANY) != 0)
    return -1;
  for (key = 0; key < XDP_JACCARD_GENERATED_RULE_COUNT; key++)
    if (bpf_map_update_elem(rules_fd, &key, &xdp_jaccard_generated_rules[key],
                            BPF_ANY) != 0)
      return -1;
  for (key = 0; key < XDP_JACCARD_GENERATED_KEYWORD_COUNT; key++)
    if (bpf_map_update_elem(keywords_fd, &key,
                            &xdp_jaccard_generated_keywords[key], BPF_ANY) != 0)
      return -1;
  for (key = 0; key < XDP_JACCARD_GENERATED_KEYWORD_COUNT; key++)
    for (__u32 gram_index = 0;
         gram_index < xdp_jaccard_generated_keywords[key].count; gram_index++)
      for (__u8 occurrence = 1;
           occurrence <=
           xdp_jaccard_generated_keywords[key].gram_counts[gram_index];
           occurrence++) {
        struct xdp_jaccard_gram_key gram_key = {
            .gram = xdp_jaccard_generated_keywords[key].grams[gram_index],
            .occurrence = occurrence,
        };
        struct xdp_jaccard_gram_vector vector = {};
        bpf_map_lookup_elem(grams_fd, &gram_key, &vector);
        if (key < 8)
          vector.low |= 1ULL << (key * XDP_JACCARD_INTERSECTION_BITS);
        else
          vector.high |= 1ULL << ((key - 8) * XDP_JACCARD_INTERSECTION_BITS);
        if (bpf_map_update_elem(grams_fd, &gram_key, &vector, BPF_ANY) != 0)
          return -1;
      }
  for (key = 0; key < XDP_JACCARD_GENERATED_CASEFOLD_COUNT; key++)
    if (bpf_map_update_elem(casefolds_fd,
                            &xdp_jaccard_generated_casefolds[key].from,
                            &xdp_jaccard_generated_casefolds[key].to,
                            BPF_ANY) != 0)
      return -1;
  return 0;
}
#endif

#include "bpf/xdp_keyword_policy_loader.h"

static int route_to_backend_port(__u32 route) {
  if (route == XDP_ROUTE_CODING)
    return BACKEND_CODING_PORT;
  if (route == XDP_ROUTE_MATH)
    return BACKEND_MATH_PORT;
  if (route == XDP_ROUTE_QA)
    return BACKEND_QA_PORT;
  if (route == XDP_ROUTE_WRITING)
    return BACKEND_WRITING_PORT;
  return BACKEND_OTHERS_PORT;
}

static int populate_xdp_tail_calls(struct bpf_object *obj) {
  int map_fd = bpf_object__find_map_fd_by_name(obj, "xdp_tail_calls");
  struct bpf_program *decoder =
      bpf_object__find_program_by_name(obj, "xdp_decode_classify");
  __u32 key = 0;
  int prog_fd;

  if (map_fd < 0 || !decoder)
    return -1;
  prog_fd = bpf_program__fd(decoder);
  if (prog_fd < 0)
    return -1;
  return bpf_map_update_elem(map_fd, &key, &prog_fd, BPF_ANY);
}

static int start_xdp_classifier(struct xdp_classifier_runtime *runtime) {
  const char *ifname = getenv("XDP_IFNAME");
  struct bpf_program *prog = NULL;
  int rules_fd;
  int ifindex;

  memset(runtime, 0, sizeof(*runtime));
  runtime->decisions_fd = -1;
  if (!ifname || !*ifname)
    ifname = "veth0";

  ifindex = if_nametoindex(ifname);
  if (!ifindex) {
    fprintf(stderr, "failed to resolve XDP interface %s: %s\n", ifname,
            strerror(errno));
    return -1;
  }

  runtime->obj = bpf_object__open_file(XDP_BPF_OBJECT_FILE, NULL);
  if (libbpf_get_error(runtime->obj)) {
    fprintf(stderr, "failed to open %s\n", XDP_BPF_OBJECT_FILE);
    runtime->obj = NULL;
    return -1;
  }

  if (bpf_object__load(runtime->obj) != 0) {
    fprintf(stderr, "failed to load %s\n", XDP_BPF_OBJECT_FILE);
    return -1;
  }

  if (populate_xdp_tail_calls(runtime->obj) != 0) {
    perror("populate_xdp_tail_calls");
    return -1;
  }

  if (populate_keyword_policy(runtime->obj) != 0) {
    perror("populate_keyword_policy");
    return -1;
  }

  rules_fd =
      bpf_object__find_map_fd_by_name(runtime->obj, "xdp_decision_rules");
  if (rules_fd < 0 || populate_decision_rules(rules_fd) != 0) {
    perror("populate_decision_rules");
    return -1;
  }

  runtime->decisions_fd =
      bpf_object__find_map_fd_by_name(runtime->obj, "xdp_flow_decisions");
  if (runtime->decisions_fd < 0) {
    fprintf(stderr, "failed to find xdp_flow_decisions map\n");
    return -1;
  }

  prog = bpf_object__find_program_by_name(runtime->obj, XDP_PROGRAM_NAME);
  if (!prog) {
    fprintf(stderr, "failed to find XDP program: %s\n", XDP_PROGRAM_NAME);
    return -1;
  }

  bpf_xdp_detach(ifindex, XDP_FLAGS_SKB_MODE, NULL);
  bpf_xdp_detach(ifindex, XDP_FLAGS_DRV_MODE, NULL);
  bpf_xdp_detach(ifindex, XDP_FLAGS_HW_MODE, NULL);
  bpf_xdp_detach(ifindex, 0, NULL);
  runtime->link = bpf_program__attach_xdp(prog, ifindex);
  if (libbpf_get_error(runtime->link)) {
    fprintf(stderr, "failed to attach XDP classifier to %s\n", ifname);
    runtime->link = NULL;
    return -1;
  }

  printf("XDP ngram classifier attached to %s\n", ifname);
  fflush(stdout);
  return 0;
}

static void stop_xdp_classifier(struct xdp_classifier_runtime *runtime) {
  if (runtime->link)
    bpf_link__destroy(runtime->link);
  if (runtime->obj)
    bpf_object__close(runtime->obj);
}

static int verify_backend_available(int port) {
  int fd = connect_backend(port);

  if (fd < 0)
    return -1;

  close(fd);
  return 0;
}

static int send_all(int fd, const char *buf, size_t len) {
  size_t sent = 0;

  while (sent < len) {
    ssize_t n = send(fd, buf + sent, len - sent, MSG_NOSIGNAL);
    if (n <= 0)
      return -1;
    sent += (size_t)n;
  }

  return 0;
}

static char ascii_lower(char c) {
  if (c >= 'A' && c <= 'Z')
    return (char)(c + ('a' - 'A'));
  return c;
}

static const char *find_headers_end(const char *buf, size_t len) {
  if (len < 4)
    return NULL;

  for (size_t i = 0; i + 4 <= len; i++) {
    if (buf[i] == '\r' && buf[i + 1] == '\n' && buf[i + 2] == '\r' &&
        buf[i + 3] == '\n')
      return buf + i + 4;
  }

  return NULL;
}

static int starts_with_ci(const char *value, const char *prefix) {
  while (*prefix) {
    if (ascii_lower(*value++) != *prefix++)
      return 0;
  }
  return 1;
}

static size_t parse_content_length(const char *headers, size_t header_len) {
  const char *line = headers;
  const char *end = headers + header_len;

  while (line < end) {
    const char *next = strstr(line, "\r\n");
    const char *line_end = next && next < end ? next : end;

    if (starts_with_ci(line, "content-length:")) {
      const char *p = line + 15;
      size_t value = 0;

      while (p < line_end && (*p == ' ' || *p == '\t'))
        p++;
      while (p < line_end && *p >= '0' && *p <= '9') {
        value = value * 10 + (size_t)(*p - '0');
        p++;
      }
      return value;
    }

    if (!next || next >= end)
      break;
    line = next + 2;
  }

  return 0;
}

static int read_http_message(int fd, char *buf, size_t cap, size_t *len_out) {
  size_t used = 0;
  const char *headers_end = NULL;
  size_t content_length;
  size_t total_len;

  while (!headers_end) {
    ssize_t n;

    if (used == cap) {
      errno = EMSGSIZE;
      return -1;
    }
    n = recv(fd, buf + used, cap - used, 0);
    if (n <= 0)
      return (n == 0 && used == 0) ? 0 : -1;
    used += (size_t)n;
    headers_end = find_headers_end(buf, used);
  }

  content_length = parse_content_length(buf, (size_t)(headers_end - buf));
  total_len = (size_t)(headers_end - buf) + content_length;
  if (total_len > cap) {
    errno = EMSGSIZE;
    return -1;
  }

  while (used < total_len) {
    ssize_t n = recv(fd, buf + used, total_len - used, 0);
    if (n <= 0)
      return -1;
    used += (size_t)n;
  }

  *len_out = total_len;
  return 1;
}

static int build_xdp_decision_key(int client_fd, struct xdp_flow_key *key) {
  struct sockaddr_in peer = {};
  struct sockaddr_in local = {};
  socklen_t peer_len = sizeof(peer);
  socklen_t local_len = sizeof(local);

  if (getpeername(client_fd, (struct sockaddr *)&peer, &peer_len) != 0 ||
      getsockname(client_fd, (struct sockaddr *)&local, &local_len) != 0)
    return -1;
  if (peer.sin_family != AF_INET || local.sin_family != AF_INET) {
    errno = EAFNOSUPPORT;
    return -1;
  }

  key->src_ip = peer.sin_addr.s_addr;
  key->dst_ip = local.sin_addr.s_addr;
  key->src_port = ntohs(peer.sin_port);
  key->dst_port = ntohs(local.sin_port);
  return 0;
}

static int select_backend_port_from_xdp(int decisions_fd, int client_fd) {
  struct xdp_flow_key key = {};
  struct xdp_flow_decision decision = {};
  char src[INET_ADDRSTRLEN] = {};
  char dst[INET_ADDRSTRLEN] = {};

  if (build_xdp_decision_key(client_fd, &key) != 0)
    return -1;

  for (int attempt = 0; attempt < 1000; attempt++) {
    if (bpf_map_lookup_elem(decisions_fd, &key, &decision) == 0) {
      bpf_map_delete_elem(decisions_fd, &key);
      return route_to_backend_port(decision.route);
    }
    usleep(100);
  }

  inet_ntop(AF_INET, &key.src_ip, src, sizeof(src));
  inet_ntop(AF_INET, &key.dst_ip, dst, sizeof(dst));
  fprintf(stderr, "timed out waiting for XDP decision for %s:%u -> %s:%u\n",
          src, key.src_port, dst, key.dst_port);
  errno = ETIMEDOUT;
  return -1;
}

struct proxy_client_arg {
  int client_fd;
  int decisions_fd;
};

static void *proxy_client_thread(void *arg) {
  struct proxy_client_arg *client_arg = arg;
  int client_fd = client_arg->client_fd;
  int decisions_fd = client_arg->decisions_fd;
  char *request = NULL;
  char *response = NULL;

  free(arg);
  request = malloc(MAX_HTTP_MESSAGE);
  response = malloc(MAX_HTTP_MESSAGE);
  if (!request || !response)
    goto out;

  while (running) {
    size_t request_len = 0;
    size_t response_len = 0;
    int backend_port;
    int backend_fd;
    int read_result =
        read_http_message(client_fd, request, MAX_HTTP_MESSAGE, &request_len);

    if (read_result <= 0) {
#ifdef XDP_DEBUG
      fprintf(stderr,
              "failed to read complete HTTP request: result=%d errno=%d\n",
              read_result, errno);
#endif
      break;
    }

    backend_port = select_backend_port_from_xdp(decisions_fd, client_fd);
    if (backend_port < 0)
      break;

    backend_fd = connect_backend(backend_port);
    if (backend_fd < 0) {
#ifdef XDP_DEBUG
      fprintf(stderr, "failed to connect backend port %d: %s\n", backend_port,
              strerror(errno));
#endif
      break;
    }

    if (send_all(backend_fd, request, request_len) != 0) {
#ifdef XDP_DEBUG
      fprintf(stderr, "failed to send request to backend: %s\n",
              strerror(errno));
#endif
      close(backend_fd);
      break;
    }

    if (read_http_message(backend_fd, response, MAX_HTTP_MESSAGE,
                          &response_len) <= 0) {
#ifdef XDP_DEBUG
      fprintf(stderr, "failed to read backend response: %s\n", strerror(errno));
#endif
      close(backend_fd);
      break;
    }

    if (send_all(client_fd, response, response_len) != 0) {
#ifdef XDP_DEBUG
      fprintf(stderr, "failed to send response to client: %s\n",
              strerror(errno));
#endif
      close(backend_fd);
      break;
    }

    close(backend_fd);
  }

out:
  free(request);
  free(response);
  close(client_fd);
  return NULL;
}

static int run_proxy_router(void) {
  struct xdp_classifier_runtime xdp = {};
  int listener_fd;

  bump_memlock_rlimit();
  if (start_xdp_classifier(&xdp) != 0) {
    stop_xdp_classifier(&xdp);
    return 1;
  }

  listener_fd = create_listener();

  if (listener_fd < 0) {
    perror("listen frontend");
    stop_xdp_classifier(&xdp);
    return 1;
  }

  printf("XDP-classified routing proxy listening on 0.0.0.0:%d\n",
         FRONTEND_PORT);
  printf("routes: coding=%d math=%d others=%d qa=%d writing=%d\n",
         BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT,
         BACKEND_QA_PORT, BACKEND_WRITING_PORT);
  fflush(stdout);

  while (running) {
    int client_fd = accept(listener_fd, NULL, NULL);
    struct proxy_client_arg *thread_arg;
    pthread_t thread;

    if (client_fd < 0) {
      if (errno == EINTR)
        continue;
      perror("accept");
      break;
    }

    set_reuse_and_nodelay(client_fd);
    thread_arg = malloc(sizeof(*thread_arg));
    if (!thread_arg) {
      close(client_fd);
      continue;
    }
    thread_arg->client_fd = client_fd;
    thread_arg->decisions_fd = xdp.decisions_fd;

    if (pthread_create(&thread, NULL, proxy_client_thread, thread_arg) != 0) {
      free(thread_arg);
      close(client_fd);
      continue;
    }
    pthread_detach(thread);
  }

  close(listener_fd);
  stop_xdp_classifier(&xdp);
  return 0;
}

static void bump_memlock_rlimit(void) {
  struct rlimit rlim = {
      .rlim_cur = RLIM_INFINITY,
      .rlim_max = RLIM_INFINITY,
  };

  if (setrlimit(RLIMIT_MEMLOCK, &rlim) != 0)
    fprintf(stderr, "warning: failed to raise RLIMIT_MEMLOCK: %s\n",
            strerror(errno));
}

static int add_connection_set(int sock_map_fd, int routes_fd, int client_fd,
                              __u32 *next_slot) {
  int coding_fd = -1;
  int math_fd = -1;
  int others_fd = -1;
  int qa_fd = -1;
  int writing_fd = -1;
  __u32 client_slot = (*next_slot)++;
  __u32 coding_slot = (*next_slot)++;
  __u32 math_slot = (*next_slot)++;
  __u32 others_slot = (*next_slot)++;
  __u32 qa_slot = (*next_slot)++;
  __u32 writing_slot = (*next_slot)++;
  struct sk_route_entry client_entry = {
      .client_slot = client_slot,
      .coding_slot = coding_slot,
      .math_slot = math_slot,
      .others_slot = others_slot,
      .qa_slot = qa_slot,
      .writing_slot = writing_slot,
      .flags = 0,
  };
  struct sk_route_entry backend_entry = {
      .client_slot = client_slot,
      .coding_slot = coding_slot,
      .math_slot = math_slot,
      .others_slot = others_slot,
      .qa_slot = qa_slot,
      .writing_slot = writing_slot,
      .flags = SK_ROUTER_FLAG_BACKEND,
  };

  if (*next_slot >= MAX_SOCK_SLOTS) {
    errno = ENOSPC;
    return -1;
  }

  coding_fd = connect_backend(BACKEND_CODING_PORT);
  math_fd = connect_backend(BACKEND_MATH_PORT);
  others_fd = connect_backend(BACKEND_OTHERS_PORT);
  qa_fd = connect_backend(BACKEND_QA_PORT);
  writing_fd = connect_backend(BACKEND_WRITING_PORT);
  if (coding_fd < 0 || math_fd < 0 || others_fd < 0 || qa_fd < 0 ||
      writing_fd < 0)
    goto fail;

  if (update_route(routes_fd, client_fd, &client_entry) != 0) {
    perror("update client route");
    goto fail;
  }
  if (update_route(routes_fd, coding_fd, &backend_entry) != 0) {
    perror("update coding route");
    goto fail;
  }
  if (update_route(routes_fd, math_fd, &backend_entry) != 0) {
    perror("update math route");
    goto fail;
  }
  if (update_route(routes_fd, others_fd, &backend_entry) != 0) {
    perror("update others route");
    goto fail;
  }
  if (update_route(routes_fd, qa_fd, &backend_entry) != 0) {
    perror("update qa route");
    goto fail;
  }
  if (update_route(routes_fd, writing_fd, &backend_entry) != 0) {
    perror("update writing route");
    goto fail;
  }

  if (update_sock_map(sock_map_fd, client_slot, client_fd) != 0) {
    perror("update client sockmap");
    goto fail;
  }
  if (update_sock_map(sock_map_fd, coding_slot, coding_fd) != 0) {
    perror("update coding sockmap");
    goto fail;
  }
  if (update_sock_map(sock_map_fd, math_slot, math_fd) != 0) {
    perror("update math sockmap");
    goto fail;
  }
  if (update_sock_map(sock_map_fd, others_slot, others_fd) != 0) {
    perror("update others sockmap");
    goto fail;
  }
  if (update_sock_map(sock_map_fd, qa_slot, qa_fd) != 0) {
    perror("update qa sockmap");
    goto fail;
  }
  if (update_sock_map(sock_map_fd, writing_slot, writing_fd) != 0) {
    perror("update writing sockmap");
    goto fail;
  }

  /* A client can send its first request while the backend connections
   * are being established.  Ask the socket layer to re-evaluate queued data
   * after the SOCKMAP programs have been attached, without consuming it. */
  {
    unsigned char byte;
    (void)recv(client_fd, &byte, sizeof(byte), MSG_PEEK | MSG_DONTWAIT);
  }

  printf("accepted client slot=%u "
         "backends={coding:%u,math:%u,others:%u,qa:%u,writing:%u}\n",
         client_slot, coding_slot, math_slot, others_slot, qa_slot,
         writing_slot);
  fflush(stdout);
  return 0;

fail:
  if (coding_fd >= 0)
    close(coding_fd);
  if (math_fd >= 0)
    close(math_fd);
  if (others_fd >= 0)
    close(others_fd);
  if (qa_fd >= 0)
    close(qa_fd);
  if (writing_fd >= 0)
    close(writing_fd);
  return -1;
}

static int run_sockmap_router(void) {
  struct bpf_object *obj = NULL;
  struct bpf_program *parser = NULL;
  struct bpf_program *verdict = NULL;
  int sock_map_fd;
  int routes_fd;
  int rules_fd;
  int listener_fd = -1;
  __u32 next_slot = 0;

  bump_memlock_rlimit();

  if (verify_backend_available(BACKEND_CODING_PORT) != 0 ||
      verify_backend_available(BACKEND_MATH_PORT) != 0 ||
      verify_backend_available(BACKEND_OTHERS_PORT) != 0 ||
      verify_backend_available(BACKEND_QA_PORT) != 0 ||
      verify_backend_available(BACKEND_WRITING_PORT) != 0) {
    fprintf(stderr,
            "required backends missing; expected coding=%d math=%d others=%d "
            "qa=%d writing=%d\n",
            BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT,
            BACKEND_QA_PORT, BACKEND_WRITING_PORT);
    return 1;
  }

  obj = bpf_object__open_file(BPF_OBJECT_FILE, NULL);
  if (libbpf_get_error(obj)) {
    fprintf(stderr, "failed to open %s\n", BPF_OBJECT_FILE);
    return 1;
  }

  if (bpf_object__load(obj) != 0) {
    fprintf(stderr, "failed to load %s\n", BPF_OBJECT_FILE);
    return 1;
  }

  parser = bpf_object__find_program_by_name(obj, "sk_router_parser");
  verdict = bpf_object__find_program_by_name(obj, "sk_router_verdict");
  sock_map_fd = bpf_object__find_map_fd_by_name(obj, "sk_sock_map");
  routes_fd = bpf_object__find_map_fd_by_name(obj, "sk_routes");
  rules_fd = bpf_object__find_map_fd_by_name(obj, "xdp_decision_rules");

  if (!parser || !verdict || sock_map_fd < 0 || routes_fd < 0 || rules_fd < 0) {
    fprintf(stderr, "failed to find required BPF programs or maps\n");
    return 1;
  }

  if (populate_decision_rules(rules_fd) != 0) {
    perror("populate_decision_rules");
    return 1;
  }
  if (populate_keyword_policy(obj) != 0) {
    perror("populate_keyword_policy");
    return 1;
  }

  if (bpf_prog_attach(bpf_program__fd(parser), sock_map_fd,
                      BPF_SK_SKB_STREAM_PARSER, 0) != 0) {
    perror("attach stream parser");
    return 1;
  }

  if (bpf_prog_attach(bpf_program__fd(verdict), sock_map_fd,
                      BPF_SK_SKB_STREAM_VERDICT, 0) != 0) {
    perror("attach stream verdict");
    return 1;
  }

  listener_fd = create_listener();
  if (listener_fd < 0) {
    perror("listen frontend");
    return 1;
  }

  printf("SK_SKB router listening on 0.0.0.0:%d\n", FRONTEND_PORT);
  printf("routes: coding=%d math=%d others=%d qa=%d writing=%d\n",
         BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT,
         BACKEND_QA_PORT, BACKEND_WRITING_PORT);
  fflush(stdout);

  while (running) {
    int client_fd = accept(listener_fd, NULL, NULL);

    if (client_fd < 0) {
      if (errno == EINTR)
        continue;
      perror("accept");
      break;
    }

    set_reuse_and_nodelay(client_fd);
    if (add_connection_set(sock_map_fd, routes_fd, client_fd, &next_slot) !=
        0) {
      perror("add_connection_set");
      close(client_fd);
    }
  }

  if (listener_fd >= 0)
    close(listener_fd);
  bpf_object__close(obj);
  return 0;
}

int main(void) {
  const char *mode;

  if (install_signal_handlers() != 0) {
    perror("install signal handlers");
    return 1;
  }

  if (verify_backend_available(BACKEND_CODING_PORT) != 0 ||
      verify_backend_available(BACKEND_MATH_PORT) != 0 ||
      verify_backend_available(BACKEND_OTHERS_PORT) != 0 ||
      verify_backend_available(BACKEND_QA_PORT) != 0 ||
      verify_backend_available(BACKEND_WRITING_PORT) != 0) {
    fprintf(stderr,
            "required backends missing; expected coding=%d math=%d others=%d "
            "qa=%d writing=%d\n",
            BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT,
            BACKEND_QA_PORT, BACKEND_WRITING_PORT);
    return 1;
  }

  mode = getenv("SK_ROUTER_MODE");
  if (mode && strcmp(mode, "proxy") == 0)
    return run_proxy_router();
  if (mode && strcmp(mode, "sockmap") != 0) {
    fprintf(stderr, "unknown SK_ROUTER_MODE '%s'; use sockmap or proxy\n",
            mode);
    return 1;
  }

  return run_sockmap_router();
}
