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
#include <linux/tcp.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/time.h>
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
#include "xsr/sk_profile.h"

#ifndef BPF_OBJECT_FILE
#define BPF_OBJECT_FILE "sk_router.bpf.o"
#endif
#define FRONTEND_PORT 18081
#define BACKEND_HOST "127.0.0.1"
#define BACKEND_CODING_PORT 18391
#define BACKEND_MATH_PORT 18392
#define BACKEND_OTHERS_PORT 18393
#define BACKEND_QA_PORT 18394
#define BACKEND_WRITING_PORT 18395

#define SK_ROUTER_FLAG_BACKEND 1
#define SK_LIFECYCLE_REQUEST_FORWARDED 1
#define SK_LIFECYCLE_REQUEST_INCOMPLETE 2
#define SK_LIFECYCLE_REDIRECT_FAILED 4
#define SK_MODEL_CODING 1
#define SK_MODEL_MATH 2
#define SK_MODEL_OTHERS 3
#define SK_MODEL_QA 4
#define SK_MODEL_WRITING 5
#define MAX_SOCK_SLOTS 16384
#ifdef XSR_FORWARDING_ONLY
#define SOCKS_PER_CONNECTION 2
#else
#define SOCKS_PER_CONNECTION 6
#endif
#define MAX_CONNECTION_SETS (MAX_SOCK_SLOTS / SOCKS_PER_CONNECTION)
#define MAX_LIFECYCLE_EVENTS 256
#define LIFECYCLE_POLL_INTERVAL_NS (100ULL * 1000 * 1000)

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
#ifdef SK_PROFILE_COMPONENTS
  int profile_components_fd;
#endif
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
  __u64 request_bytes_processed;
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

static int verify_backend_available(int port) {
  int fd = connect_backend(port);

  if (fd < 0)
    return -1;

  close(fd);
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
#ifdef XSR_DEBUG
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
#ifdef XSR_FORWARDING_ONLY
      0, BACKEND_CODING_PORT,
#else
      0, BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT,
      BACKEND_QA_PORT, BACKEND_WRITING_PORT,
#endif
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
#ifdef XSR_FORWARDING_ONLY
  client_entry.math_slot = backend_entry.math_slot = set->slots[1];
  client_entry.others_slot = backend_entry.others_slot = set->slots[1];
  client_entry.qa_slot = backend_entry.qa_slot = set->slots[1];
  client_entry.writing_slot = backend_entry.writing_slot = set->slots[1];
#else
  client_entry.math_slot = backend_entry.math_slot = set->slots[2];
  client_entry.others_slot = backend_entry.others_slot = set->slots[3];
  client_entry.qa_slot = backend_entry.qa_slot = set->slots[4];
  client_entry.writing_slot = backend_entry.writing_slot = set->slots[5];
#endif

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

#ifdef XSR_FORWARDING_ONLY
  printf("accepted client slot=%u fixed-backend slot=%u\n", set->slots[0],
         set->slots[1]);
#else
  printf("accepted client slot=%u "
         "backends={coding:%u,math:%u,others:%u,qa:%u,writing:%u}\n",
         set->slots[0], set->slots[1], set->slots[2], set->slots[3],
         set->slots[4], set->slots[5]);
#endif
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

#ifdef SK_PROFILE_COMPONENTS
static int serve_profile_read(int fd, int map_fd) {
  struct sk_profile_value *values;
  int cpu_count = libbpf_num_possible_cpus();

  if (cpu_count <= 0)
    return dprintf(fd, "profile_enabled=1 error=cpu_count\n") < 0 ? -1 : 0;
  values = calloc((size_t)SK_PROFILE_STAGE_COUNT * cpu_count, sizeof(*values));
  if (!values)
    return dprintf(fd, "profile_enabled=1 error=allocation\n") < 0 ? -1 : 0;
  for (__u32 stage = 0; stage < SK_PROFILE_STAGE_COUNT; stage++) {
    if (bpf_map_lookup_elem(map_fd, &stage, values + (size_t)stage * cpu_count) !=
        0) {
      free(values);
      return dprintf(fd, "profile_enabled=1 error=map_lookup\n") < 0 ? -1 : 0;
    }
  }

  dprintf(fd, "profile_enabled=1 cpu_count=%d stage_count=%d\n", cpu_count,
          SK_PROFILE_STAGE_COUNT);
  for (int cpu = 0; cpu < cpu_count; cpu++) {
    const struct sk_profile_value *parse =
        &values[(size_t)SK_PROFILE_PARSE_SIGNAL * cpu_count + cpu];
    const struct sk_profile_value *decision =
        &values[(size_t)SK_PROFILE_DECISION * cpu_count + cpu];
    const struct sk_profile_value *redirect =
        &values[(size_t)SK_PROFILE_REDIRECT * cpu_count + cpu];

    dprintf(fd,
            "cpu=%d parse_signal_count=%llu parse_signal_total_ns=%llu "
            "decision_count=%llu decision_total_ns=%llu redirect_count=%llu "
            "redirect_total_ns=%llu\n",
            cpu, (unsigned long long)parse->count,
            (unsigned long long)parse->total_ns,
            (unsigned long long)decision->count,
            (unsigned long long)decision->total_ns,
            (unsigned long long)redirect->count,
            (unsigned long long)redirect->total_ns);
  }
  free(values);
  return 0;
}

static int serve_profile_reset(int fd, int map_fd) {
  struct sk_profile_value *zeros;
  int cpu_count = libbpf_num_possible_cpus();

  if (cpu_count <= 0)
    return dprintf(fd, "profile_enabled=1 error=cpu_count\n") < 0 ? -1 : 0;
  zeros = calloc((size_t)cpu_count, sizeof(*zeros));
  if (!zeros)
    return dprintf(fd, "profile_enabled=1 error=allocation\n") < 0 ? -1 : 0;
  for (__u32 stage = 0; stage < SK_PROFILE_STAGE_COUNT; stage++) {
    if (bpf_map_update_elem(map_fd, &stage, zeros, BPF_ANY) != 0) {
      free(zeros);
      return dprintf(fd, "profile_enabled=1 error=map_update\n") < 0 ? -1 : 0;
    }
  }
  free(zeros);
  return dprintf(fd, "profile_enabled=1 reset=ok\n") < 0 ? -1 : 0;
}
#endif

static void serve_status(struct connection_manager *manager) {
  int fd;

  while ((fd = accept4(manager->status_fd, NULL, NULL,
                       SOCK_CLOEXEC)) >= 0) {
    char command[64] = {};
    struct timeval timeout = {.tv_usec = 20000};
    size_t command_len = 0;

    /* New clients send an explicit command. The short timeout preserves the
     * original connect-and-read status protocol for older benchmark tools. */
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    while (command_len < sizeof(command) - 1) {
      ssize_t received = recv(fd, command + command_len,
                              sizeof(command) - 1 - command_len, 0);

      if (received <= 0)
        break;
      command_len += (size_t)received;
      if (memchr(command, '\n', command_len))
        break;
    }
    if (command_len) {
      command[command_len] = '\0';
      command[strcspn(command, "\r\n")] = '\0';
    } else {
      strcpy(command, "status");
    }

#ifdef SK_PROFILE_COMPONENTS
    if (strcmp(command, "profile read") == 0) {
      serve_profile_read(fd, manager->profile_components_fd);
      close(fd);
      continue;
    }
    if (strcmp(command, "profile reset") == 0) {
      serve_profile_reset(fd, manager->profile_components_fd);
      close(fd);
      continue;
    }
#else
    if (strcmp(command, "profile read") == 0 ||
        strcmp(command, "profile reset") == 0) {
      dprintf(fd, "profile_enabled=0 error=profiling_disabled\n");
      close(fd);
      continue;
    }
#endif

    if (strcmp(command, "status") != 0) {
      dprintf(fd, "error=unknown_command\n");
      close(fd);
      continue;
    }
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
      __u64 request_bytes;
      __u32 backend_fin_count = 0;

      if (!set->peer_write_closed) {
        set->peer_write_closed = 1;
        manager->half_close_total++;
      }
      if (get_tcp_info(set->fds[CONNECTION_CLIENT], &info) != 0) {
        reap_connection_set(manager, manager->poll_set_indices[i],
                            "frontend TCP state unavailable");
        continue;
      }
      /* tcpi_bytes_received includes the peer FIN's sequence byte once
       * POLLRDHUP is visible. */
      request_bytes = info.tcpi_bytes_received > 0
                          ? info.tcpi_bytes_received - 1
                          : 0;
      if (request_bytes == 0) {
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
        if (lifecycle.flags & SK_LIFECYCLE_REDIRECT_FAILED) {
          reap_connection_set(manager, manager->poll_set_indices[i],
                              "frontend request redirect failed");
        } else if ((lifecycle.flags & SK_LIFECYCLE_REQUEST_INCOMPLETE) &&
                   lifecycle.request_bytes_processed >= request_bytes) {
          reap_connection_set(manager, manager->poll_set_indices[i],
                              "frontend half-close with incomplete request");
        }
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
  memset(manager, 0, sizeof(*manager));
  manager->epoll_fd = -1;
  manager->status_fd = -1;
  manager->timer_fd = -1;
  manager->sock_map_fd = sock_map_fd;
  manager->routes_fd = routes_fd;
  manager->http_flows_fd = http_flows_fd;
  manager->route_decisions_fd = route_decisions_fd;
  manager->lifecycle_fd = lifecycle_fd;
  manager->sets = calloc(MAX_CONNECTION_SETS, sizeof(*manager->sets));
  manager->free_sets = calloc(MAX_CONNECTION_SETS, sizeof(*manager->free_sets));
  manager->poll_set_indices =
      calloc(MAX_CONNECTION_SETS, sizeof(*manager->poll_set_indices));
  manager->poll_fds = calloc(MAX_CONNECTION_SETS, sizeof(*manager->poll_fds));
  if (!manager->sets || !manager->free_sets || !manager->poll_set_indices ||
      !manager->poll_fds)
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
#ifdef SK_PROFILE_COMPONENTS
  int profile_components_fd;
#endif
  int rules_fd;
  int listener_fd = -1;

  bump_memlock_rlimit();
  if (ensure_sockmap_nofile_limit() != 0) {
    perror("raise SOCKMAP file descriptor limit");
    return 1;
  }

  if (verify_backend_available(BACKEND_CODING_PORT) != 0
#ifndef XSR_FORWARDING_ONLY
      ||
      verify_backend_available(BACKEND_MATH_PORT) != 0 ||
      verify_backend_available(BACKEND_OTHERS_PORT) != 0 ||
      verify_backend_available(BACKEND_QA_PORT) != 0 ||
      verify_backend_available(BACKEND_WRITING_PORT) != 0
#endif
  ) {
#ifdef XSR_FORWARDING_ONLY
    fprintf(stderr, "required fixed backend missing; expected coding=%d\n",
            BACKEND_CODING_PORT);
#else
    fprintf(stderr,
            "required backends missing; expected coding=%d math=%d others=%d "
            "qa=%d writing=%d\n",
            BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT,
            BACKEND_QA_PORT, BACKEND_WRITING_PORT);
#endif
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
#ifdef SK_PROFILE_COMPONENTS
  profile_components_fd =
      bpf_object__find_map_fd_by_name(obj, "sk_profile_components");
#endif
  rules_fd = bpf_object__find_map_fd_by_name(obj, "xdp_decision_rules");

  if (!parser || !verdict || sock_map_fd < 0 || routes_fd < 0 ||
      http_flows_fd < 0 || route_decisions_fd < 0 || lifecycle_fd < 0 ||
#ifdef SK_PROFILE_COMPONENTS
      profile_components_fd < 0 ||
#endif
      rules_fd < 0) {
    fprintf(stderr, "failed to find required BPF programs or maps\n");
    return 1;
  }

#ifndef XSR_FORWARDING_ONLY
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
#else
  printf("XSR forwarding-only ablation: fixed backend=coding; semantic routing disabled\n");
  fflush(stdout);
#endif

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
#ifdef SK_PROFILE_COMPONENTS
  manager.profile_components_fd = profile_components_fd;
#endif
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
#ifdef XSR_FORWARDING_ONLY
  printf("fixed route: coding=%d (all other backend sockets omitted)\n",
         BACKEND_CODING_PORT);
#else
  printf("routes: coding=%d math=%d others=%d qa=%d writing=%d\n",
         BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT,
         BACKEND_QA_PORT, BACKEND_WRITING_PORT);
#ifdef SK_PROFILE_COMPONENTS
  printf("SK_SKB component profiling enabled\n");
#endif
#endif
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

  if (verify_backend_available(BACKEND_CODING_PORT) != 0
#ifndef XSR_FORWARDING_ONLY
      ||
      verify_backend_available(BACKEND_MATH_PORT) != 0 ||
      verify_backend_available(BACKEND_OTHERS_PORT) != 0 ||
      verify_backend_available(BACKEND_QA_PORT) != 0 ||
      verify_backend_available(BACKEND_WRITING_PORT) != 0
#endif
  ) {
#ifdef XSR_FORWARDING_ONLY
    fprintf(stderr, "required fixed backend missing; expected coding=%d\n",
            BACKEND_CODING_PORT);
#else
    fprintf(stderr,
            "required backends missing; expected coding=%d math=%d others=%d "
            "qa=%d writing=%d\n",
            BACKEND_CODING_PORT, BACKEND_MATH_PORT, BACKEND_OTHERS_PORT,
            BACKEND_QA_PORT, BACKEND_WRITING_PORT);
#endif
    return 1;
  }

  mode = getenv("SK_ROUTER_MODE");
  if (mode && strcmp(mode, "distill") == 0 &&
      (!getenv("XSR_DISTILL_MODEL") || !*getenv("XSR_DISTILL_MODEL"))) {
    fprintf(stderr, "distill mode requires XSR_DISTILL_MODEL\n");
    return 1;
  }
  if (mode && strcmp(mode, "sockmap") != 0 && strcmp(mode, "distill") != 0) {
    fprintf(stderr, "unknown SK_ROUTER_MODE '%s'; use sockmap or distill\n",
            mode);
    return 1;
  }

  return run_sockmap_router();
}
