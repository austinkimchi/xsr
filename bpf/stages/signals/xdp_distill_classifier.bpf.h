#ifndef XDP_DISTILL_CLASSIFIER_BPF_H
#define XDP_DISTILL_CLASSIFIER_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>
#include <bpf/bpf_helpers.h>
#include "xsr/distill_model_format.h"

#define XDP_DISTILL_CLASSES XSR_DISTILL_CLASSES
#define XDP_DISTILL_BUCKETS XSR_DISTILL_BUCKETS
#define XDP_DISTILL_PROMPT_BYTES XSR_DISTILL_PROMPT_BYTES

struct xdp_distill_bucket { __s8 weight[XDP_DISTILL_CLASSES]; };
struct xdp_distill_config {
  __s32 bias[XDP_DISTILL_CLASSES];
  __u32 enabled;
  __u32 prompt_byte_limit;
  __u32 proven_score_bound;
};
#if XSR_DISTILL_PARITY_DEBUG
struct xdp_distill_debug {
  __s32 score[XDP_DISTILL_CLASSES];
  __u32 intent;
  __u32 bytes_seen;
};
#endif

struct {
  __uint(type, BPF_MAP_TYPE_ARRAY);
  __uint(max_entries, XDP_DISTILL_BUCKETS);
  __type(key, __u32);
  __type(value, struct xdp_distill_bucket);
} xdp_distill_weights SEC(".maps");
struct {
  __uint(type, BPF_MAP_TYPE_ARRAY);
  __uint(max_entries, 1);
  __type(key, __u32);
  __type(value, struct xdp_distill_config);
} xdp_distill_config_map SEC(".maps");
#if XSR_DISTILL_PARITY_DEBUG
/* Sequential parity tests read this diagnostic map; routing never consumes it. */
struct {
  __uint(type, BPF_MAP_TYPE_ARRAY);
  __uint(max_entries, 1);
  __type(key, __u32);
  __type(value, struct xdp_distill_debug);
} xdp_distill_last_prediction SEC(".maps");
#endif

struct xdp_distill_state {
  __s32 score[XDP_DISTILL_CLASSES];
  __u32 bytes_seen;
  __u8 previous_1;
  __u8 previous_2;
};

static __always_inline void xdp_distill_init(struct xdp_distill_state *state) {
  __u32 key = 0;
  struct xdp_distill_config *config = bpf_map_lookup_elem(&xdp_distill_config_map, &key);
  if (!config || !config->enabled)
    return;
#pragma unroll
  for (int c = 0; c < XDP_DISTILL_CLASSES; c++)
    state->score[c] = config->bias[c];
}

static __always_inline __u8 xdp_distill_ascii_lower(__u8 value) {
  return value >= 'A' && value <= 'Z' ? value + ('a' - 'A') : value;
}

static __always_inline void xdp_distill_score_char(struct xdp_distill_state *state, __u8 value) {
  struct xdp_distill_bucket *weights;
  __u32 hash, bucket;
  if (state->bytes_seen >= XDP_DISTILL_PROMPT_BYTES)
    return;
  value = xdp_distill_ascii_lower(value);
  state->bytes_seen++;
  if (state->bytes_seen < 3) {
    state->previous_2 = state->previous_1;
    state->previous_1 = value;
    return;
  }
  hash = 2166136261U;
  hash = (hash ^ state->previous_2) * 16777619U;
  hash = (hash ^ state->previous_1) * 16777619U;
  hash = (hash ^ value) * 16777619U;
  bucket = hash & (XDP_DISTILL_BUCKETS - 1);
  weights = bpf_map_lookup_elem(&xdp_distill_weights, &bucket);
  if (weights) {
#pragma unroll
    for (int c = 0; c < XDP_DISTILL_CLASSES; c++)
      state->score[c] += weights->weight[c];
  }
  state->previous_2 = state->previous_1;
  state->previous_1 = value;
}

static __always_inline __u32 xdp_distill_intent(struct xdp_distill_state *state, __u8 *enabled) {
  __u32 key = 0, best = 0;
  struct xdp_distill_config *config = bpf_map_lookup_elem(&xdp_distill_config_map, &key);
  if (!config || !config->enabled) {
    *enabled = 0;
    return 0;
  }
  *enabled = 1;
#pragma unroll
  for (int c = 1; c < XDP_DISTILL_CLASSES; c++)
    if (state->score[c] > state->score[best])
      best = c;
#if XSR_DISTILL_PARITY_DEBUG
  struct xdp_distill_debug *debug = bpf_map_lookup_elem(&xdp_distill_last_prediction, &key);
  if (debug) {
#pragma unroll
    for (int c = 0; c < XDP_DISTILL_CLASSES; c++)
      debug->score[c] = state->score[c];
    debug->intent = best;
    debug->bytes_seen = state->bytes_seen;
  }
#endif
  return best;
}

static __always_inline __u32 xdp_distill_route(struct xdp_distill_state *state, __u8 *enabled) {
  __u32 intent = xdp_distill_intent(state, enabled);
  if (!*enabled)
    return XDP_ROUTE_GENERAL;
  if (intent == 3)
    return XDP_ROUTE_CODING;
  if (intent == 9)
    return XDP_ROUTE_MATH;
  return XDP_ROUTE_GENERAL;
}
#endif
