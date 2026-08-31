#define _GNU_SOURCE

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
#include <linux/tcp.h>
#include <net/if.h>
#include <netinet/in.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/timerfd.h>
#include <sys/un.h>
#include <unistd.h>

#include "stages/signals/generated/xdp_keyword_modules.generated.h"
#if XDP_KEYWORD_ENABLE_NGRAM
#include "stages/signals/xdp_ngram_classifier.bpf.h"
#include "stages/signals/generated/xdp_jaccard_policy.generated.h"
#endif
#if XDP_KEYWORD_ENABLE_BM25
#include "stages/signals/xdp_bm25_classifier.bpf.h"
#include "stages/signals/generated/xdp_bm25_policy.generated.h"
#endif
#include "stages/signals/domains.bpf.h"
#include "xsr/distill_model_loader.h"
#include "xsr/router.h"

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
#define SK_LIFECYCLE_REQUEST_FORWARDED 1
#define SK_MODEL_CODING 1
#define SK_MODEL_MATH 2
#define SK_MODEL_OTHERS 3
#define SK_MODEL_QA 4
#define SK_MODEL_WRITING 5
#define MAX_SOCK_SLOTS 16384
#define SOCKS_PER_CONNECTION 6
#define MAX_CONNECTION_SETS (MAX_SOCK_SLOTS / SOCKS_PER_CONNECTION)
#define MAX_LIFECYCLE_EVENTS 256
#define LIFECYCLE_POLL_INTERVAL_NS (100ULL * 1000 * 1000)
#define MAX_HTTP_MESSAGE (256 * 1024)

enum connection_member {
  CONNECTION_CLIENT,
  CONNECTION_CODING,
  CONNECTION_MATH,
  CONNECTION_OTHERS,
  CONNECTION_QA,
  CONNECTION_WRITING,
};

struct connection_set {
  int fds[SOCKS_PER_CONNECTION];
  __u32 slots[SOCKS_PER_CONNECTION];
  __u64 cookies[SOCKS_PER_CONNECTION];
  __u64 initial_backend_bytes_received;
  unsigned char allocated;
  unsigned char active;
  unsigned char peer_write_closed;
  unsigned char backend_writes_shutdown;
  unsigned char drain_confirmed;
  unsigned char lifecycle_installed;
  unsigned char sockmap_installed[SOCKS_PER_CONNECTION];
  unsigned char route_installed[SOCKS_PER_CONNECTION];
};

struct connection_manager {
  struct connection_set *sets;
  __u32 *free_sets;
  __u32 *poll_set_indices;
  struct pollfd *poll_fds;
  __u32 free_count;
  __u32 active_count;
  __u32 quarantined_count;
  __u32 sockmap_entry_count;
  __u64 accepted_total;
  __u64 reaped_total;
  __u64 half_close_total;
  __u64 lifecycle_poll_total;
  int epoll_fd;
  int sock_map_fd;
  int routes_fd;
  int http_flows_fd;
  int route_decisions_fd;
  int lifecycle_fd;
  void *http_flow_value;
  int status_fd;
  int timer_fd;
  char status_path[sizeof(((struct sockaddr_un *)0)->sun_path)];
};

#define LIFECYCLE_LISTENER_EVENT UINT64_MAX
#define LIFECYCLE_STATUS_EVENT (UINT64_MAX - 1)
#define LIFECYCLE_TIMER_EVENT (UINT64_MAX - 2)

struct xdp_decision_rule {
  __u64 require_any;
  __u64 require_all;
  __u64 reject_any;
  __u32 model_id;
  __u32 enabled;
};

struct sk_route_entry {
  __u64 client_cookie;
  __u32 client_slot;
  __u32 coding_slot;
  __u32 math_slot;
  __u32 others_slot;
  __u32 qa_slot;
  __u32 writing_slot;
  __u32 flags;
};

struct sk_lifecycle_state {
  __u64 response_bytes_forwarded;
  __u32 flags;
  __u32 reserved;
};

static volatile sig_atomic_t running = 1;

static int frontend_port(void) {
  const char *value = getenv("XSR_FRONTEND_PORT");
  char *end = NULL;
  long port;

  if (!value || !*value)
    return FRONTEND_PORT;
  port = strtol(value, &end, 10);
  return end && !*end && port > 0 && port <= 65535 ? (int)port : -1;
}

struct xdp_classifier_runtime {
  struct bpf_object *obj;
  struct bpf_link *link;
  int decisions_fd;
};

static void bump_memlock_rlimit(void);
static int ensure_sockmap_nofile_limit(void);

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
  int port = frontend_port();

  if (fd < 0 || port < 0) {
    if (fd >= 0)
      close(fd);
    errno = EINVAL;
    return -1;
  }

  set_reuse_and_nodelay(fd);
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons(port);

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

static int update_route(int routes_fd, __u64 cookie,
                        const struct sk_route_entry *entry) {
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

#include "xsr/keyword_policy_loader.h"

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
  if (populate_distill_model(runtime->obj, getenv("XSR_DISTILL_MODEL")) != 0) {
    perror("populate_distill_model");
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
         frontend_port());
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

static int ensure_sockmap_nofile_limit(void) {
  const rlim_t required = MAX_SOCK_SLOTS + 256;
  struct rlimit limit;

  if (getrlimit(RLIMIT_NOFILE, &limit) != 0)
    return -1;
  if (limit.rlim_cur >= required)
    return 0;
  if (limit.rlim_max < required) {
    errno = EMFILE;
    return -1;
  }
  limit.rlim_cur = required;
  return setrlimit(RLIMIT_NOFILE, &limit);
}

static int delete_map_key(int map_fd, const void *key) {
  if (bpf_map_delete_elem(map_fd, key) == 0 || errno == ENOENT)
    return 0;
  return -1;
}

static int delete_sockmap_slot(int map_fd, const __u32 *slot) {
  /* Linux SOCKMAP reports EINVAL, rather than ENOENT, for an empty valid
   * array slot. All allocator-produced slots are range-checked by design. */
  if (bpf_map_delete_elem(map_fd, slot) == 0 || errno == EINVAL)
    return 0;
  return -1;
}

static void reset_connection_set(struct connection_set *set) {
  for (int member = 0; member < SOCKS_PER_CONNECTION; member++)
    set->fds[member] = -1;
  memset(set->cookies, 0, sizeof(set->cookies));
  set->initial_backend_bytes_received = 0;
  memset(set->sockmap_installed, 0, sizeof(set->sockmap_installed));
  memset(set->route_installed, 0, sizeof(set->route_installed));
  set->allocated = 0;
  set->active = 0;
  set->peer_write_closed = 0;
  set->backend_writes_shutdown = 0;
  set->drain_confirmed = 0;
  set->lifecycle_installed = 0;
}

static int get_tcp_info(int fd, struct tcp_info *info) {
  socklen_t info_len = sizeof(*info);

  memset(info, 0, sizeof(*info));
  return getsockopt(fd, IPPROTO_TCP, TCP_INFO, info, &info_len);
}

static void shutdown_backend_writes(struct connection_set *set) {
  for (int member = 1; member < SOCKS_PER_CONNECTION; member++)
    if (set->fds[member] >= 0 && shutdown(set->fds[member], SHUT_WR) != 0 &&
        errno != ENOTCONN)
      fprintf(stderr, "warning: backend write shutdown failed: %s\n",
              strerror(errno));
  set->backend_writes_shutdown = 1;
}

static int backend_responses_complete(const struct connection_set *set,
                                      __u32 *fin_count) {
  struct pollfd backends[SOCKS_PER_CONNECTION - 1];
  int ready;

  for (int member = 1; member < SOCKS_PER_CONNECTION; member++) {
    backends[member - 1].fd = set->fds[member];
    backends[member - 1].events = POLLRDHUP | POLLHUP | POLLERR;
    backends[member - 1].revents = 0;
  }
  ready = poll(backends, SOCKS_PER_CONNECTION - 1, 0);
  if (ready < 0)
    return 0;
  *fin_count = 0;
  for (int member = 1; member < SOCKS_PER_CONNECTION; member++)
    if (!(backends[member - 1].revents &
          (POLLRDHUP | POLLHUP | POLLERR | POLLNVAL)))
      return 0;
    else if (backends[member - 1].revents & POLLRDHUP)
      (*fin_count)++;
  return 1;
}

static int backend_bytes_received(const struct connection_set *set,
                                  __u64 *bytes_received) {
  __u64 total = 0;

  for (int member = 1; member < SOCKS_PER_CONNECTION; member++) {
    struct tcp_info info;

    if (get_tcp_info(set->fds[member], &info) != 0)
      return -1;
    total += info.tcpi_bytes_received;
  }
  *bytes_received = total;
  return 0;
}

static int reap_connection_set(struct connection_manager *manager,
                               __u32 set_index, const char *reason) {
  struct connection_set *set = &manager->sets[set_index];
  int cleanup_failed = 0;
  int was_active;

  if (!set->allocated)
    return 0;

  was_active = set->active;
  if (was_active) {
    set->active = 0;
    manager->active_count--;
  }

  /* Explicit deletion makes slot availability deterministic. Kernel close
   * also unlinks SOCKMAP entries, but it does not remove XSR's cookie-keyed
   * hash maps, and a peer FIN alone does neither while userspace owns the FD. */
  for (int member = 0; member < SOCKS_PER_CONNECTION; member++) {
    if (set->sockmap_installed[member] &&
        delete_sockmap_slot(manager->sock_map_fd, &set->slots[member]) != 0)
      cleanup_failed = 1;
    else if (set->sockmap_installed[member]) {
      set->sockmap_installed[member] = 0;
      manager->sockmap_entry_count--;
    }
  }
  for (int member = 0; member < SOCKS_PER_CONNECTION; member++) {
    if (set->route_installed[member] &&
        delete_map_key(manager->routes_fd, &set->cookies[member]) != 0)
      cleanup_failed = 1;
    else
      set->route_installed[member] = 0;
  }
  if (set->cookies[CONNECTION_CLIENT]) {
    if (delete_map_key(manager->http_flows_fd,
                       &set->cookies[CONNECTION_CLIENT]) != 0)
      cleanup_failed = 1;
    if (set->lifecycle_installed &&
        delete_map_key(manager->lifecycle_fd,
                       &set->cookies[CONNECTION_CLIENT]) != 0)
      cleanup_failed = 1;
    else
      set->lifecycle_installed = 0;
    if (delete_map_key(manager->route_decisions_fd,
                       &set->cookies[CONNECTION_CLIENT]) != 0)
      cleanup_failed = 1;
  }

  for (int member = 0; member < SOCKS_PER_CONNECTION; member++) {
    if (set->fds[member] >= 0) {
      close(set->fds[member]);
      set->fds[member] = -1;
    }
  }

  /* If an explicit SOCKMAP delete raced with kernel close, retry after close.
   * Never recycle the six-slot block unless every old key is confirmed gone. */
  if (cleanup_failed) {
    cleanup_failed = 0;
    for (int member = 0; member < SOCKS_PER_CONNECTION; member++) {
      if (set->sockmap_installed[member] &&
          delete_sockmap_slot(manager->sock_map_fd, &set->slots[member]) != 0)
        cleanup_failed = 1;
      else if (set->sockmap_installed[member]) {
        set->sockmap_installed[member] = 0;
        manager->sockmap_entry_count--;
      }
      if (set->route_installed[member] &&
          delete_map_key(manager->routes_fd, &set->cookies[member]) != 0)
        cleanup_failed = 1;
      else
        set->route_installed[member] = 0;
    }
    if (set->cookies[CONNECTION_CLIENT] &&
        (delete_map_key(manager->http_flows_fd,
                        &set->cookies[CONNECTION_CLIENT]) != 0 ||
         delete_map_key(manager->route_decisions_fd,
                        &set->cookies[CONNECTION_CLIENT]) != 0))
      cleanup_failed = 1;
    if (set->lifecycle_installed &&
        delete_map_key(manager->lifecycle_fd,
                       &set->cookies[CONNECTION_CLIENT]) != 0)
      cleanup_failed = 1;
    else
      set->lifecycle_installed = 0;
  }

  if (cleanup_failed) {
    manager->quarantined_count++;
    set->allocated = 0;
    fprintf(stderr, "quarantined connection slots starting at %u after cleanup failure (%s)\n",
            set->slots[0], reason);
    return -1;
  }

  reset_connection_set(set);
  manager->free_sets[manager->free_count++] = set_index;
  if (was_active)
    manager->reaped_total++;
#ifdef XDP_DEBUG
  fprintf(stderr, "reaped connection slots starting at %u (%s)\n",
          set_index * SOCKS_PER_CONNECTION, reason);
#else
  (void)reason;
#endif
  return 0;
}

static int add_connection_set(struct connection_manager *manager,
                              int client_fd) {
  static const int backend_ports[SOCKS_PER_CONNECTION] = {
      0, BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT,
      BACKEND_QA_PORT, BACKEND_WRITING_PORT,
  };
  __u32 set_index;
  struct connection_set *set;
  struct sk_route_entry client_entry = {
      .flags = 0,
  };
  struct sk_route_entry backend_entry = {
      .flags = SK_ROUTER_FLAG_BACKEND,
  };
  struct sk_lifecycle_state lifecycle = {};

  if (!manager->free_count) {
    errno = ENOSPC;
    close(client_fd);
    return -1;
  }

  set_index = manager->free_sets[--manager->free_count];
  set = &manager->sets[set_index];
  reset_connection_set(set);
  set->allocated = 1;
  set->fds[CONNECTION_CLIENT] = client_fd;
  set->peer_write_closed = 0;
  set->backend_writes_shutdown = 0;
  set->drain_confirmed = 0;
  set->lifecycle_installed = 0;

  for (int member = 1; member < SOCKS_PER_CONNECTION; member++) {
    set->fds[member] = connect_backend(backend_ports[member]);
    if (set->fds[member] < 0)
      goto fail;
  }

  for (int member = 0; member < SOCKS_PER_CONNECTION; member++) {
    if (get_socket_cookie(set->fds[member], &set->cookies[member]) != 0)
      goto fail;
  }
  if (backend_bytes_received(set, &set->initial_backend_bytes_received) != 0)
    goto fail;

  client_entry.client_cookie = backend_entry.client_cookie =
      set->cookies[CONNECTION_CLIENT];
  if (bpf_map_update_elem(manager->lifecycle_fd,
                          &set->cookies[CONNECTION_CLIENT], &lifecycle,
                          BPF_NOEXIST) != 0) {
    perror("initialize lifecycle state");
    goto fail;
  }
  set->lifecycle_installed = 1;

  client_entry.client_slot = backend_entry.client_slot = set->slots[0];
  client_entry.coding_slot = backend_entry.coding_slot = set->slots[1];
  client_entry.math_slot = backend_entry.math_slot = set->slots[2];
  client_entry.others_slot = backend_entry.others_slot = set->slots[3];
  client_entry.qa_slot = backend_entry.qa_slot = set->slots[4];
  client_entry.writing_slot = backend_entry.writing_slot = set->slots[5];

  for (int member = 0; member < SOCKS_PER_CONNECTION; member++) {
    const struct sk_route_entry *entry =
        member == CONNECTION_CLIENT ? &client_entry : &backend_entry;

    if (update_route(manager->routes_fd, set->cookies[member], entry) != 0) {
      perror("update socket route");
      goto fail;
    }
    set->route_installed[member] = 1;
  }

  for (int member = 0; member < SOCKS_PER_CONNECTION; member++) {
    if (update_sock_map(manager->sock_map_fd, set->slots[member],
                        set->fds[member]) != 0) {
      fprintf(stderr, "update sockmap member=%d slot=%u fd=%d: %s\n", member,
              set->slots[member], set->fds[member], strerror(errno));
      goto fail;
    }
    set->sockmap_installed[member] = 1;
    manager->sockmap_entry_count++;
  }

  set->active = 1;
  manager->active_count++;

  /* A client can send its first request while the backend connections
   * are being established.  Ask the socket layer to re-evaluate queued data
   * after the SOCKMAP programs have been attached, without consuming it. */
  {
    unsigned char byte;
    (void)recv(client_fd, &byte, sizeof(byte), MSG_PEEK | MSG_DONTWAIT);
  }

  printf("accepted client slot=%u "
         "backends={coding:%u,math:%u,others:%u,qa:%u,writing:%u}\n",
         set->slots[0], set->slots[1], set->slots[2], set->slots[3],
         set->slots[4], set->slots[5]);
  fflush(stdout);
  manager->accepted_total++;
  return 0;

fail:
  reap_connection_set(manager, set_index, "connection setup failure");
  return -1;
}

static int create_status_listener(struct connection_manager *manager) {
  const char *path = getenv("XSR_STATUS_SOCKET");
  struct sockaddr_un addr = {.sun_family = AF_UNIX};
  struct epoll_event event = {
      .events = EPOLLIN,
      .data.u64 = LIFECYCLE_STATUS_EVENT,
  };

  if (!path || !*path)
    return 0;
  if (strlen(path) >= sizeof(addr.sun_path)) {
    errno = ENAMETOOLONG;
    return -1;
  }
  manager->status_fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC,
                              0);
  if (manager->status_fd < 0)
    return -1;
  strcpy(addr.sun_path, path);
  strcpy(manager->status_path, path);
  unlink(path);
  if (bind(manager->status_fd, (struct sockaddr *)&addr, sizeof(addr)) != 0 ||
      listen(manager->status_fd, 16) != 0 ||
      epoll_ctl(manager->epoll_fd, EPOLL_CTL_ADD, manager->status_fd, &event) !=
          0)
    return -1;
  return 0;
}

static int count_map_entries(int map_fd, size_t key_size) {
  unsigned char current[sizeof(__u64)] = {};
  unsigned char next[sizeof(__u64)] = {};
  const void *key = NULL;
  int count = 0;

  if (key_size > sizeof(current)) {
    errno = EINVAL;
    return -1;
  }
  while (bpf_map_get_next_key(map_fd, key, next) == 0) {
    count++;
    memcpy(current, next, key_size);
    key = current;
  }
  return errno == ENOENT ? count : -1;
}

static int map_contains_key(int map_fd, const void *key, void *value) {
  if (bpf_map_lookup_elem(map_fd, key, value) == 0)
    return 1;
  return errno == ENOENT ? 0 : -1;
}

static void serve_status(struct connection_manager *manager) {
  int fd;

  while ((fd = accept4(manager->status_fd, NULL, NULL,
                       SOCK_NONBLOCK | SOCK_CLOEXEC)) >= 0) {
    int sockmap_entries = manager->sockmap_entry_count;
    int routes_entries = count_map_entries(manager->routes_fd, sizeof(__u64));
    int http_flows_entries =
        count_map_entries(manager->http_flows_fd, sizeof(__u64));
    int route_decisions_entries =
        count_map_entries(manager->route_decisions_fd, sizeof(__u64));
    int lifecycle_entries =
        count_map_entries(manager->lifecycle_fd, sizeof(__u64));

    dprintf(fd,
            "pid=%ld active_connection_sets=%u free_slot_sets=%u "
            "quarantined_slot_sets=%u accepted_total=%llu reaped_total=%llu "
            "half_close_total=%llu "
            "lifecycle_poll_total=%llu "
            "sockmap_entries=%d routes_entries=%d http_flows_entries=%d "
            "route_decisions_entries=%d lifecycle_entries=%d\n",
            (long)getpid(), manager->active_count, manager->free_count,
            manager->quarantined_count,
            (unsigned long long)manager->accepted_total,
            (unsigned long long)manager->reaped_total,
            (unsigned long long)manager->half_close_total,
            (unsigned long long)manager->lifecycle_poll_total,
            sockmap_entries, routes_entries, http_flows_entries,
            route_decisions_entries, lifecycle_entries);
    close(fd);
  }
}

static void poll_connection_lifecycle(struct connection_manager *manager) {
  __u64 expirations;
  __u32 count = 0;
  int ready;

  if (read(manager->timer_fd, &expirations, sizeof(expirations)) !=
      sizeof(expirations))
    return;
  manager->lifecycle_poll_total += expirations;
  for (__u32 i = 0; i < MAX_CONNECTION_SETS; i++) {
    if (!manager->sets[i].active)
      continue;
    manager->poll_fds[count].fd =
        manager->sets[i].fds[CONNECTION_CLIENT];
    manager->poll_fds[count].events = POLLRDHUP | POLLHUP | POLLERR;
    manager->poll_fds[count].revents = 0;
    manager->poll_set_indices[count] = i;
    count++;
  }
  ready = poll(manager->poll_fds, count, 0);
  if (ready < 0) {
    if (errno != EINTR)
      perror("poll connection lifecycle");
    return;
  }
  for (__u32 i = 0; i < count && ready > 0; i++) {
    struct connection_set *set;
    short revents = manager->poll_fds[i].revents;

    if (!(revents & (POLLRDHUP | POLLHUP | POLLERR | POLLNVAL)))
      continue;
    ready--;
    set = &manager->sets[manager->poll_set_indices[i]];
    if (revents & (POLLHUP | POLLERR | POLLNVAL)) {
      reap_connection_set(manager, manager->poll_set_indices[i],
                          "frontend failed or fully closed");
      continue;
    }
    if (revents & POLLRDHUP) {
      struct tcp_info info;
      struct sk_lifecycle_state lifecycle;
      __u64 received = 0;
      __u32 backend_fin_count = 0;
      int flow_present;

      if (!set->peer_write_closed) {
        set->peer_write_closed = 1;
        manager->half_close_total++;
      }
      if (get_tcp_info(set->fds[CONNECTION_CLIENT], &info) != 0) {
        reap_connection_set(manager, manager->poll_set_indices[i],
                            "frontend TCP state unavailable");
        continue;
      }
      flow_present =
          map_contains_key(manager->http_flows_fd,
                           &set->cookies[CONNECTION_CLIENT],
                           manager->http_flow_value);
      if (flow_present < 0)
        continue;
      if (info.tcpi_bytes_received == 0) {
        reap_connection_set(manager, manager->poll_set_indices[i],
                            "frontend half-close without request");
        continue;
      }
      if (bpf_map_lookup_elem(manager->lifecycle_fd,
                              &set->cookies[CONNECTION_CLIENT],
                              &lifecycle) != 0) {
        reap_connection_set(manager, manager->poll_set_indices[i],
                            "frontend lifecycle state unavailable");
        continue;
      }
      if (!(lifecycle.flags & SK_LIFECYCLE_REQUEST_FORWARDED)) {
        if (flow_present)
          reap_connection_set(manager, manager->poll_set_indices[i],
                              "frontend half-close with incomplete request");
        continue;
      }
      if (!set->backend_writes_shutdown)
        shutdown_backend_writes(set);
      int backend_complete =
          backend_responses_complete(set, &backend_fin_count);
      int received_status = backend_bytes_received(set, &received);
      /* Linux includes each received FIN's sequence byte in
       * tcpi_bytes_received; the BPF counter contains payload bytes only. */
      if (backend_complete && received_status == 0 &&
          received >=
              set->initial_backend_bytes_received + backend_fin_count &&
          lifecycle.response_bytes_forwarded >=
              received - set->initial_backend_bytes_received -
                  backend_fin_count &&
          info.tcpi_unacked == 0 && info.tcpi_notsent_bytes == 0) {
        if (set->drain_confirmed)
          reap_connection_set(manager, manager->poll_set_indices[i],
                              "frontend half-close drained");
        else
          set->drain_confirmed = 1;
      } else {
        set->drain_confirmed = 0;
      }
    }
  }
}

static int initialize_connection_manager(struct connection_manager *manager,
                                         int sock_map_fd, int routes_fd,
                                         int http_flows_fd,
                                         int route_decisions_fd,
                                         int lifecycle_fd) {
  struct bpf_map_info http_flow_info = {};
  __u32 http_flow_info_len = sizeof(http_flow_info);

  memset(manager, 0, sizeof(*manager));
  manager->epoll_fd = -1;
  manager->status_fd = -1;
  manager->timer_fd = -1;
  manager->sock_map_fd = sock_map_fd;
  manager->routes_fd = routes_fd;
  manager->http_flows_fd = http_flows_fd;
  manager->route_decisions_fd = route_decisions_fd;
  manager->lifecycle_fd = lifecycle_fd;
  if (bpf_obj_get_info_by_fd(http_flows_fd, &http_flow_info,
                             &http_flow_info_len) != 0 ||
      !http_flow_info.value_size)
    return -1;
  manager->http_flow_value = malloc(http_flow_info.value_size);
  manager->sets = calloc(MAX_CONNECTION_SETS, sizeof(*manager->sets));
  manager->free_sets = calloc(MAX_CONNECTION_SETS, sizeof(*manager->free_sets));
  manager->poll_set_indices =
      calloc(MAX_CONNECTION_SETS, sizeof(*manager->poll_set_indices));
  manager->poll_fds = calloc(MAX_CONNECTION_SETS, sizeof(*manager->poll_fds));
  if (!manager->http_flow_value || !manager->sets || !manager->free_sets ||
      !manager->poll_set_indices || !manager->poll_fds)
    return -1;

  for (__u32 i = 0; i < MAX_CONNECTION_SETS; i++) {
    reset_connection_set(&manager->sets[i]);
    for (__u32 member = 0; member < SOCKS_PER_CONNECTION; member++)
      manager->sets[i].slots[member] = i * SOCKS_PER_CONNECTION + member;
    manager->free_sets[i] = MAX_CONNECTION_SETS - i - 1;
  }
  manager->free_count = MAX_CONNECTION_SETS;
  manager->epoll_fd = epoll_create1(EPOLL_CLOEXEC);
  if (manager->epoll_fd < 0)
    return -1;
  manager->timer_fd =
      timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
  if (manager->timer_fd < 0)
    return -1;
  {
    struct itimerspec timer = {
        .it_interval = {
            .tv_sec = LIFECYCLE_POLL_INTERVAL_NS / 1000000000ULL,
            .tv_nsec = LIFECYCLE_POLL_INTERVAL_NS % 1000000000ULL,
        },
        .it_value = {
            .tv_sec = LIFECYCLE_POLL_INTERVAL_NS / 1000000000ULL,
            .tv_nsec = LIFECYCLE_POLL_INTERVAL_NS % 1000000000ULL,
        },
    };
    struct epoll_event event = {
        .events = EPOLLIN,
        .data.u64 = LIFECYCLE_TIMER_EVENT,
    };

    if (timerfd_settime(manager->timer_fd, 0, &timer, NULL) != 0 ||
        epoll_ctl(manager->epoll_fd, EPOLL_CTL_ADD, manager->timer_fd,
                  &event) != 0)
      return -1;
  }
  if (create_status_listener(manager) != 0)
    return -1;
  return 0;
}

static void destroy_connection_manager(struct connection_manager *manager) {
  for (__u32 i = 0; i < MAX_CONNECTION_SETS; i++)
    if (manager->sets && manager->sets[i].allocated)
      reap_connection_set(manager, i, "router shutdown");
  if (manager->status_fd >= 0)
    close(manager->status_fd);
  if (manager->timer_fd >= 0)
    close(manager->timer_fd);
  if (manager->status_path[0])
    unlink(manager->status_path);
  if (manager->epoll_fd >= 0)
    close(manager->epoll_fd);
  free(manager->sets);
  free(manager->free_sets);
  free(manager->poll_set_indices);
  free(manager->poll_fds);
  free(manager->http_flow_value);
}

static int run_sockmap_router(void) {
  struct connection_manager manager;
  struct bpf_object *obj = NULL;
  struct bpf_program *parser = NULL;
  struct bpf_program *verdict = NULL;
  int sock_map_fd;
  int routes_fd;
  int http_flows_fd;
  int route_decisions_fd;
  int lifecycle_fd;
  int rules_fd;
  int listener_fd = -1;

  bump_memlock_rlimit();
  if (ensure_sockmap_nofile_limit() != 0) {
    perror("raise SOCKMAP file descriptor limit");
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
  http_flows_fd = bpf_object__find_map_fd_by_name(obj, "sk_http_flows");
  route_decisions_fd =
      bpf_object__find_map_fd_by_name(obj, "sk_route_decisions");
  lifecycle_fd = bpf_object__find_map_fd_by_name(obj, "sk_lifecycle");
  rules_fd = bpf_object__find_map_fd_by_name(obj, "xdp_decision_rules");

  if (!parser || !verdict || sock_map_fd < 0 || routes_fd < 0 ||
      http_flows_fd < 0 || route_decisions_fd < 0 || lifecycle_fd < 0 ||
      rules_fd < 0) {
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
  if (populate_distill_model(obj, getenv("XSR_DISTILL_MODEL")) != 0) {
    perror("populate_distill_model");
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

  if (initialize_connection_manager(&manager, sock_map_fd, routes_fd,
                                    http_flows_fd, route_decisions_fd,
                                    lifecycle_fd) != 0) {
    perror("initialize connection manager");
    destroy_connection_manager(&manager);
    close(listener_fd);
    return 1;
  }
  {
    struct epoll_event event = {
        .events = EPOLLIN,
        .data.u64 = LIFECYCLE_LISTENER_EVENT,
    };
    if (epoll_ctl(manager.epoll_fd, EPOLL_CTL_ADD, listener_fd, &event) != 0) {
      perror("monitor listener");
      destroy_connection_manager(&manager);
      close(listener_fd);
      return 1;
    }
  }

  printf("SK_SKB router listening on 0.0.0.0:%d\n", frontend_port());
  printf("routes: coding=%d math=%d others=%d qa=%d writing=%d\n",
         BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT,
         BACKEND_QA_PORT, BACKEND_WRITING_PORT);
  fflush(stdout);

  while (running) {
    struct epoll_event events[MAX_LIFECYCLE_EVENTS];
    int event_count =
        epoll_wait(manager.epoll_fd, events, MAX_LIFECYCLE_EVENTS, -1);

    if (event_count < 0) {
      if (errno == EINTR)
        continue;
      perror("epoll_wait");
      break;
    }
    for (int i = 0; i < event_count; i++) {
      __u64 tag = events[i].data.u64;

      if (tag == LIFECYCLE_LISTENER_EVENT) {
        int client_fd = accept(listener_fd, NULL, NULL);

        if (client_fd < 0) {
          if (errno != EINTR && errno != EAGAIN)
            perror("accept");
          continue;
        }
        set_reuse_and_nodelay(client_fd);
        if (add_connection_set(&manager, client_fd) != 0)
          perror("add_connection_set");
      } else if (tag == LIFECYCLE_STATUS_EVENT) {
        serve_status(&manager);
      } else if (tag == LIFECYCLE_TIMER_EVENT) {
        poll_connection_lifecycle(&manager);
      }
    }
  }

  if (listener_fd >= 0)
    close(listener_fd);
  destroy_connection_manager(&manager);
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
  if (mode && strcmp(mode, "distill") == 0 &&
      (!getenv("XSR_DISTILL_MODEL") || !*getenv("XSR_DISTILL_MODEL"))) {
    fprintf(stderr, "distill mode requires XSR_DISTILL_MODEL\n");
    return 1;
  }
  if (mode && strcmp(mode, "sockmap") != 0 && strcmp(mode, "distill") != 0) {
    fprintf(stderr, "unknown SK_ROUTER_MODE '%s'; use sockmap, distill, or proxy\n",
            mode);
    return 1;
  }

  return run_sockmap_router();
}
