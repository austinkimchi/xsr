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

#include "xdp_router.h"
#include "bpf/xdp_ngram_model.generated.h"
#include "bpf/xdp_signals.bpf.h"

#define BPF_OBJECT_FILE "sk_router.bpf.o"
#define FRONTEND_PORT 18081
#define BACKEND_HOST "127.0.0.1"
#define BACKEND_CODING_PORT 18391
#define BACKEND_MATH_PORT 18392
#define BACKEND_OTHERS_PORT 18393

#define SK_ROUTER_FLAG_BACKEND 1
#define SK_MODEL_CODING 1
#define SK_MODEL_MATH 2
#define SK_MODEL_OTHERS 3
#define MAX_SOCK_SLOTS 4096
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
  __u32 flags;
};

static volatile sig_atomic_t running = 1;

static void handle_signal(int sig) {
  (void)sig;
  running = 0;
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
  struct xdp_decision_rule rules[3] = {
      {.require_any = XDP_SIGNAL_DOMAIN_CODING,
       .model_id = SK_MODEL_CODING,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_MATH,
       .model_id = SK_MODEL_MATH,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_OTHERS,
       .model_id = SK_MODEL_OTHERS,
       .enabled = 1},
  };

  for (__u32 i = 0; i < 3; i++) {
    if (bpf_map_update_elem(rules_fd, &i, &rules[i], BPF_ANY) != 0)
      return -1;
  }

  for (__u32 i = 0; i < 3; i++) {
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

static int populate_ngram_weights(struct bpf_object *obj) {
  int map_fd = bpf_object__find_map_fd_by_name(obj, "xdp_ngram_weights");

  if (map_fd < 0)
    return 0;

  for (__u32 key = 0; key < XDP_NGRAM_FEATURES; key++) {
    if (bpf_map_update_elem(map_fd, &key, &xdp_ngram_model[key], BPF_ANY) != 0)
      return -1;
  }

  return 0;
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

#ifdef XDP_CLASSIFIER_LITERAL
static int contains_ci(const char *buf, size_t len, const char *needle) {
  size_t needle_len = strlen(needle);

  if (needle_len == 0 || needle_len > len)
    return 0;

  for (size_t i = 0; i + needle_len <= len; i++) {
    size_t j = 0;

    while (j < needle_len && ascii_lower(buf[i + j]) == needle[j])
      j++;
    if (j == needle_len)
      return 1;
  }

  return 0;
}
#endif

#ifndef XDP_CLASSIFIER_LITERAL
struct ngram_score {
  int coding;
  int general;
  int math;
  unsigned char seen;
  unsigned char c0;
  unsigned char c1;
  unsigned char c2;
};

static unsigned int ngram_hash3(unsigned char c0, unsigned char c1,
                                unsigned char c2) {
  unsigned int hash = 2166136261u;

  hash ^= c0;
  hash *= 16777619u;
  hash ^= c1;
  hash *= 16777619u;
  hash ^= c2;
  hash *= 16777619u;

  return hash & (XDP_NGRAM_FEATURES - 1);
}

static void ngram_score_init(struct ngram_score *score) {
  score->coding = XDP_NGRAM_BIAS_CODING;
  score->general = XDP_NGRAM_BIAS_GENERAL;
  score->math = XDP_NGRAM_BIAS_MATH;
  score->seen = 0;
  score->c0 = 0;
  score->c1 = 0;
  score->c2 = 0;
}

static void ngram_score_char(struct ngram_score *score, unsigned char c) {
  unsigned int key;
  const struct xdp_ngram_weight *weight;

  c = (unsigned char)ascii_lower((char)c);
  score->c0 = score->c1;
  score->c1 = score->c2;
  score->c2 = c;

  if (score->seen < 3) {
    score->seen++;
    if (score->seen < 3)
      return;
  }

  key = ngram_hash3(score->c0, score->c1, score->c2);
  weight = &xdp_ngram_model[key];
  score->coding += weight->coding;
  score->general += weight->general;
  score->math += weight->math;
}

static int ngram_route_for_scores(const struct ngram_score *score) {
  int route = BACKEND_CODING_PORT;
  int best = score->coding;

  if (score->general > best) {
    best = score->general;
    route = BACKEND_OTHERS_PORT;
  }

  if (score->math > best)
    route = BACKEND_MATH_PORT;

  return route;
}

static int score_first_content_string(const char *request, size_t len,
                                      struct ngram_score *score) {
  const char key[] = "\"content\"";
  int waiting_colon = 0;
  int waiting_quote = 0;

  for (size_t i = 0; i + sizeof(key) - 1 <= len; i++) {
    if (strncmp(request + i, key, sizeof(key) - 1) == 0) {
      i += sizeof(key) - 1;
      waiting_colon = 1;
    }

    if (waiting_colon) {
      while (i < len && (request[i] == ' ' || request[i] == '\t' ||
                         request[i] == '\r' || request[i] == '\n'))
        i++;
      if (i < len && request[i] == ':') {
        i++;
        waiting_quote = 1;
        waiting_colon = 0;
      } else {
        waiting_colon = 0;
      }
    }

    if (waiting_quote) {
      while (i < len && (request[i] == ' ' || request[i] == '\t' ||
                         request[i] == '\r' || request[i] == '\n'))
        i++;
      if (i >= len || request[i] != '"')
        return 0;
      i++;

      int escaped = 0;
      for (; i < len; i++) {
        unsigned char c = (unsigned char)request[i];

        if (escaped) {
          escaped = 0;
        } else if (c == '\\') {
          escaped = 1;
        } else if (c == '"') {
          return 1;
        }

        ngram_score_char(score, c);
      }
      return 0;
    }
  }

  return 0;
}
#endif

static int select_backend_port(const char *request, size_t len) {
#ifdef XDP_CLASSIFIER_LITERAL
  if (contains_ci(request, len, "debug") ||
      contains_ci(request, len, "function") ||
      contains_ci(request, len, "code") ||
      contains_ci(request, len, "algorithm") ||
      contains_ci(request, len, "refactor"))
    return BACKEND_CODING_PORT;

  if (contains_ci(request, len, "solve") ||
      contains_ci(request, len, "matrix") ||
      contains_ci(request, len, "equation") ||
      contains_ci(request, len, "derivative") ||
      contains_ci(request, len, "integral") ||
      contains_ci(request, len, "geometry") ||
      contains_ci(request, len, "calculate") ||
      contains_ci(request, len, "probability"))
    return BACKEND_MATH_PORT;

  return BACKEND_OTHERS_PORT;
#else
  struct ngram_score score;

  ngram_score_init(&score);
  if (!score_first_content_string(request, len, &score))
    return BACKEND_OTHERS_PORT;
  return ngram_route_for_scores(&score);
#endif
}

static void *proxy_client_thread(void *arg) {
  int client_fd = *(int *)arg;
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
    int backend_fd;
    int read_result = read_http_message(client_fd, request, MAX_HTTP_MESSAGE,
                                        &request_len);

    if (read_result <= 0)
      break;

    backend_fd = connect_backend(select_backend_port(request, request_len));
    if (backend_fd < 0)
      break;

    if (send_all(backend_fd, request, request_len) != 0 ||
        read_http_message(backend_fd, response, MAX_HTTP_MESSAGE,
                          &response_len) <= 0 ||
        send_all(client_fd, response, response_len) != 0) {
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
  int listener_fd = create_listener();

  if (listener_fd < 0) {
    perror("listen frontend");
    return 1;
  }

  printf("userspace routing proxy listening on 0.0.0.0:%d\n", FRONTEND_PORT);
  printf("routes: coding=%d math=%d others=%d\n", BACKEND_CODING_PORT,
         BACKEND_MATH_PORT, BACKEND_OTHERS_PORT);
  fflush(stdout);

  while (running) {
    int client_fd = accept(listener_fd, NULL, NULL);
    int *thread_fd;
    pthread_t thread;

    if (client_fd < 0) {
      if (errno == EINTR)
        continue;
      perror("accept");
      break;
    }

    set_reuse_and_nodelay(client_fd);
    thread_fd = malloc(sizeof(*thread_fd));
    if (!thread_fd) {
      close(client_fd);
      continue;
    }
    *thread_fd = client_fd;

    if (pthread_create(&thread, NULL, proxy_client_thread, thread_fd) != 0) {
      free(thread_fd);
      close(client_fd);
      continue;
    }
    pthread_detach(thread);
  }

  close(listener_fd);
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
  __u32 client_slot = (*next_slot)++;
  __u32 coding_slot = (*next_slot)++;
  __u32 math_slot = (*next_slot)++;
  __u32 others_slot = (*next_slot)++;
  struct sk_route_entry client_entry = {
      .client_slot = client_slot,
      .coding_slot = coding_slot,
      .math_slot = math_slot,
      .others_slot = others_slot,
      .flags = 0,
  };
  struct sk_route_entry backend_entry = {
      .client_slot = client_slot,
      .coding_slot = coding_slot,
      .math_slot = math_slot,
      .others_slot = others_slot,
      .flags = SK_ROUTER_FLAG_BACKEND,
  };

  if (*next_slot >= MAX_SOCK_SLOTS) {
    errno = ENOSPC;
    return -1;
  }

  coding_fd = connect_backend(BACKEND_CODING_PORT);
  math_fd = connect_backend(BACKEND_MATH_PORT);
  others_fd = connect_backend(BACKEND_OTHERS_PORT);
  if (coding_fd < 0 || math_fd < 0 || others_fd < 0)
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

  printf("accepted client slot=%u backends={coding:%u,math:%u,others:%u}\n",
         client_slot, coding_slot, math_slot, others_slot);
  fflush(stdout);
  return 0;

fail:
  if (coding_fd >= 0)
    close(coding_fd);
  if (math_fd >= 0)
    close(math_fd);
  if (others_fd >= 0)
    close(others_fd);
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

  signal(SIGINT, handle_signal);
  signal(SIGTERM, handle_signal);
  bump_memlock_rlimit();

  if (verify_backend_available(BACKEND_CODING_PORT) != 0 ||
      verify_backend_available(BACKEND_MATH_PORT) != 0 ||
      verify_backend_available(BACKEND_OTHERS_PORT) != 0) {
    fprintf(stderr,
            "required backends missing; expected coding=%d math=%d others=%d\n",
            BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT);
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
  if (populate_ngram_weights(obj) != 0) {
    perror("populate_ngram_weights");
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
  printf("routes: coding=%d math=%d others=%d\n", BACKEND_CODING_PORT,
         BACKEND_MATH_PORT, BACKEND_OTHERS_PORT);
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

  signal(SIGINT, handle_signal);
  signal(SIGTERM, handle_signal);

  if (verify_backend_available(BACKEND_CODING_PORT) != 0 ||
      verify_backend_available(BACKEND_MATH_PORT) != 0 ||
      verify_backend_available(BACKEND_OTHERS_PORT) != 0) {
    fprintf(stderr,
            "required backends missing; expected coding=%d math=%d others=%d\n",
            BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT);
    return 1;
  }

  mode = getenv("SK_ROUTER_MODE");
  if (mode && strcmp(mode, "sockmap") == 0)
    return run_sockmap_router();

  return run_proxy_router();
}
