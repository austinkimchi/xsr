/*
  Userspace XDP loader.
  This program loads the XDP program (xdp_router.bpf.c) into the kernel and
  attaches it to a network interface.
*/

// These macros could change:
#define BPF_OBJECT_FILE "xdp_router.bpf.o"
#define XDP_PROGRAM_NAME "xdp_router"
#define XDP_MAP_NAME "counters"

#include <bpf/bpf.h>
#include <bpf/libbpf.h>
#include <net/if.h> // if_nametoindex
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "xdp_router.h"
#include "bpf/xdp_ngram_model.generated.h"
#include "bpf/xdp_signals.bpf.h"

#define XDP_MODEL_CODING 1
#define XDP_MODEL_MATH 2
#define XDP_MODEL_OTHERS 3

struct xdp_decision_rule {
  __u64 require_any;
  __u64 require_all;
  __u64 reject_any;
  __u32 model_id;
  __u32 enabled;
};

struct route_counter {
  __u32 key;
  const char *route;
  const char *model;
};

static const struct route_counter route_counters[] = {
    {COUNT_ROUTE_CODING, "coding", "coding-model"},
    {COUNT_ROUTE_OTHERS, "others", "default-route"},
    {COUNT_ROUTE_MATH, "math", "math-model"},
};

#ifdef XDP_DEBUG
static const char *route_name(__u32 route) {
  switch (route) {
  case 0:
    return "coding";
  case 1:
    return "others";
  case 2:
    return "math";
  default:
    return "unknown";
  }
}

static int handle_route_event(void *ctx, void *data, size_t data_sz) {
  const struct xdp_route_event *event = data;

  (void)ctx;

  if (data_sz < sizeof(*event))
    return 0;

  printf("{\"event\":\"route\",\"src_port\":%u,\"route_name\":\"%s\",\"route\":%u,"
         "\"model_id\":%u,\"content_length\":%u,"
         "\"matched_keywords\":{\"coding\":%s,\"math\":%s},"
         "\"xdp_elapsed_ns\":%llu}\n",
         event->src_port, route_name(event->route), event->route, event->model_id,
         event->content_length, event->matched_coding ? "true" : "false",
         event->matched_math ? "true" : "false",
         (unsigned long long)event->elapsed_ns);
  return 0;
}
#endif

__u64 read_percpu_counter(int map_fd, __u32 key, int cpu_count) {
  __u64 values[cpu_count];
  __u64 total = 0;

  if (bpf_map_lookup_elem(map_fd, &key, values) != 0)
    return 0;

  for (int cpu = 0; cpu < cpu_count; cpu++)
    total += values[cpu];

  return total;
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

static int populate_decision_rules(struct bpf_object *obj) {
  int rules_fd = bpf_object__find_map_fd_by_name(obj, "xdp_decision_rules");
  struct xdp_decision_rule rules[3] = {
      {.require_any = XDP_SIGNAL_DOMAIN_CODING,
       .model_id = XDP_MODEL_CODING,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_MATH,
       .model_id = XDP_MODEL_MATH,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_OTHERS,
       .model_id = XDP_MODEL_OTHERS,
       .enabled = 1},
  };

  if (rules_fd < 0)
    return -1;

  for (__u32 i = 0; i < 3; i++) {
    if (bpf_map_update_elem(rules_fd, &i, &rules[i], BPF_ANY) != 0)
      return -1;
  }

  return 0;
}

int main(void) {
  struct bpf_object *obj;
  struct bpf_program *prog;
  struct bpf_link *link;
#ifdef XDP_DEBUG
  struct ring_buffer *route_events = NULL;
#endif

  int map_fd;
  int ifindex;

  ifindex = if_nametoindex("veth0");
  if (!ifindex) {
    perror("if_nametoindex");
    return 1;
  }

  // Load BPF object file into the kernel
  obj = bpf_object__open_file(BPF_OBJECT_FILE, NULL);
  if (libbpf_get_error(obj)) { // File might not exist
    fprintf(stderr, "Failed to open BPF object file: %s\n", BPF_OBJECT_FILE);
    return 1;
  }

  if (bpf_object__load(obj)) { // Loading the object file could fail
    fprintf(stderr, "Failed to load BPF object file: %s\n", BPF_OBJECT_FILE);
    return 1;
  }

  if (populate_ngram_weights(obj) != 0) {
    perror("populate_ngram_weights");
    return 1;
  }
  if (populate_decision_rules(obj) != 0) {
    perror("populate_decision_rules");
    return 1;
  }

  // Find XDP program by name
  prog = bpf_object__find_program_by_name(obj, XDP_PROGRAM_NAME);
  if (!prog) { // Program might not exist
    fprintf(stderr, "Failed to find XDP program: %s\n", XDP_PROGRAM_NAME);
    return 1;
  }

  // Attach XDP program to the network interface with retry loop
  for (int retry = 0; retry < 5; retry++) {
    link = bpf_program__attach_xdp(prog, ifindex);
    if (!libbpf_get_error(link))
      break;
    usleep(200000);
  }
  if (libbpf_get_error(link)) { // Attaching the program could fail
    fprintf(stderr, "Failed to attach XDP program to interface index: %d\n",
            ifindex);
    return 1;
  }

  // Find the map file descriptor by name
  map_fd = bpf_object__find_map_fd_by_name(obj, XDP_MAP_NAME);
  if (map_fd < 0) {
    fprintf(stderr, "Failed to find map: counters\n");
    return 1;
  }

  printf("XDP attached to interface index %d\n", ifindex);
  printf("Counters map FD: %d\n", map_fd);
  printf("Waiting for OpenAI prompt routes...\n");
  fflush(stdout);

#ifdef XDP_DEBUG
  int event_map_fd = bpf_object__find_map_fd_by_name(obj, "xdp_route_events");
  if (event_map_fd >= 0) {
    route_events = ring_buffer__new(event_map_fd, handle_route_event, NULL, NULL);
    if (!route_events)
      fprintf(stderr, "Failed to open xdp_route_events ring buffer\n");
  }
#endif

  int cpu_count = libbpf_num_possible_cpus();
  __u64 last_counts[sizeof(route_counters) / sizeof(route_counters[0])] = {};

  if (cpu_count < 0) {
    fprintf(stderr, "Failed to read possible CPU count\n");
    return 1;
  }

  for (size_t i = 0; i < sizeof(route_counters) / sizeof(route_counters[0]);
       i++) {
    last_counts[i] =
        read_percpu_counter(map_fd, route_counters[i].key, cpu_count);
  }

  while (1) {
#ifdef XDP_DEBUG
    if (route_events)
      ring_buffer__poll(route_events, 100);
    else
      sleep(1);
#else
    sleep(1);
#endif

    for (size_t i = 0; i < sizeof(route_counters) / sizeof(route_counters[0]);
         i++) {
      __u64 current =
          read_percpu_counter(map_fd, route_counters[i].key, cpu_count);

      for (__u64 count = last_counts[i]; count < current; count++) {
        printf("prompt routed: route=%s model=%s total=%llu\n",
               route_counters[i].route, route_counters[i].model,
               (unsigned long long)(count + 1));
      }

      last_counts[i] = current;
    }

    fflush(stdout);
  }

#ifdef XDP_DEBUG
  ring_buffer__free(route_events);
#endif
  bpf_link__destroy(link);
  bpf_object__close(obj);
  return 0;
}
