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
#include <linux/if_link.h>
#include <net/if.h> // if_nametoindex
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "xsr/router.h"
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

#define XDP_MODEL_CODING 1
#define XDP_MODEL_MATH 2
#define XDP_MODEL_OTHERS 3
#define XDP_MODEL_QA 4
#define XDP_MODEL_WRITING 5

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
    {COUNT_ROUTE_QA, "qa", "qa-model"},
    {COUNT_ROUTE_WRITING, "writing", "writing-model"},
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
  case 3:
    return "qa";
  case 4:
    return "writing";
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
         "\"matched_keywords\":{\"coding\":%s,\"math\":%s,\"qa\":%s,\"writing\":%s},"
         "\"xdp_elapsed_ns\":%llu}\n",
         event->src_port, route_name(event->route), event->route, event->model_id,
         event->content_length, event->matched_coding ? "true" : "false",
         event->matched_math ? "true" : "false",
         event->matched_qa ? "true" : "false",
         event->matched_writing ? "true" : "false",
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

#if XDP_KEYWORD_ENABLE_NGRAM
static int populate_jaccard_policy(struct bpf_object *obj) {
  int config_fd = bpf_object__find_map_fd_by_name(obj, "xdp_jaccard_config");
  int rules_fd = bpf_object__find_map_fd_by_name(obj, "xdp_jaccard_rules");
  int keywords_fd = bpf_object__find_map_fd_by_name(obj, "xdp_jaccard_keywords");
  int grams_fd = bpf_object__find_map_fd_by_name(obj, "xdp_jaccard_gram_masks");
  int casefolds_fd = bpf_object__find_map_fd_by_name(obj, "xdp_jaccard_casefolds");
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
           occurrence <= xdp_jaccard_generated_keywords[key].gram_counts[gram_index]; occurrence++) {
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

static int populate_decision_rules(struct bpf_object *obj) {
  int rules_fd = bpf_object__find_map_fd_by_name(obj, "xdp_decision_rules");
  struct xdp_decision_rule rules[5] = {
      {.require_any = XDP_SIGNAL_DOMAIN_CODING,
       .model_id = XDP_MODEL_CODING,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_MATH,
       .model_id = XDP_MODEL_MATH,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_QA,
       .model_id = XDP_MODEL_QA,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_WRITING,
       .model_id = XDP_MODEL_WRITING,
       .enabled = 1},
      {.require_any = XDP_SIGNAL_DOMAIN_OTHERS,
       .model_id = XDP_MODEL_OTHERS,
       .enabled = 1},
  };

  if (rules_fd < 0)
    return -1;

  for (__u32 i = 0; i < 5; i++) {
    if (bpf_map_update_elem(rules_fd, &i, &rules[i], BPF_ANY) != 0)
      return -1;
  }

  return 0;
}

static int populate_tail_calls(struct bpf_object *obj) {
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

  if (populate_keyword_policy(obj) != 0) {
    perror("populate_keyword_policy");
    return 1;
  }
  if (populate_distill_model(obj, getenv("XSR_DISTILL_MODEL")) != 0) {
    perror("populate_distill_model");
    return 1;
  }
  if (populate_decision_rules(obj) != 0) {
    perror("populate_decision_rules");
    return 1;
  }
  if (populate_tail_calls(obj) != 0) {
    perror("populate_tail_calls");
    return 1;
  }

  // Find XDP program by name
  prog = bpf_object__find_program_by_name(obj, XDP_PROGRAM_NAME);
  if (!prog) { // Program might not exist
    fprintf(stderr, "Failed to find XDP program: %s\n", XDP_PROGRAM_NAME);
    return 1;
  }

  bpf_xdp_detach(ifindex, XDP_FLAGS_SKB_MODE, NULL);
  bpf_xdp_detach(ifindex, XDP_FLAGS_DRV_MODE, NULL);
  bpf_xdp_detach(ifindex, XDP_FLAGS_HW_MODE, NULL);
  bpf_xdp_detach(ifindex, 0, NULL);

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
