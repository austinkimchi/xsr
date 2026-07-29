#ifndef XDP_NGRAM_CLASSIFIER_BPF_H
#define XDP_NGRAM_CLASSIFIER_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>

#include <bpf/bpf_helpers.h>

#include "xdp_router.h"

#define XDP_NGRAM_SIZE 3
#define XDP_NGRAM_MASK (XDP_NGRAM_FEATURES - 1)

#define XDP_NGRAM_BIAS_CODING -178
#define XDP_NGRAM_BIAS_GENERAL 154
#define XDP_NGRAM_BIAS_REASONING 24

enum xdp_ngram_route {
  XDP_NGRAM_ROUTE_CODING = 0,
  XDP_NGRAM_ROUTE_GENERAL = 1,
  XDP_NGRAM_ROUTE_REASONING = 2,
};

struct xdp_ngram_state {
  __s32 coding;
  __s32 general;
  __s32 reasoning;
  __u8 seen;
  unsigned char c0;
  unsigned char c1;
  unsigned char c2;
};

struct {
  __uint(type, BPF_MAP_TYPE_ARRAY);
  __uint(max_entries, XDP_NGRAM_FEATURES);
  __type(key, __u32);
  __type(value, struct xdp_ngram_weight);
} xdp_ngram_weights SEC(".maps");

static __always_inline void xdp_ngram_init(struct xdp_ngram_state *state) {
  state->coding = XDP_NGRAM_BIAS_CODING;
  state->general = XDP_NGRAM_BIAS_GENERAL;
  state->reasoning = XDP_NGRAM_BIAS_REASONING;
  state->seen = 0;
  state->c0 = 0;
  state->c1 = 0;
  state->c2 = 0;
}

static __always_inline int
xdp_ngram_is_initialized(struct xdp_ngram_state *state) {
  return state->coding != 0 || state->general != 0 || state->reasoning != 0 ||
         state->seen != 0;
}

static __always_inline unsigned char xdp_ngram_lower(unsigned char c) {
  if (c >= 'A' && c <= 'Z')
    return c + ('a' - 'A');
  return c;
}

static __always_inline __u32 xdp_ngram_hash3(unsigned char c0, unsigned char c1,
                                             unsigned char c2) {
  __u32 hash = 2166136261u;

  hash ^= c0;
  hash *= 16777619u;
  hash ^= c1;
  hash *= 16777619u;
  hash ^= c2;
  hash *= 16777619u;

  return hash & XDP_NGRAM_MASK;
}

static __always_inline void xdp_ngram_score_char(struct xdp_ngram_state *state,
                                                 unsigned char c) {
  struct xdp_ngram_weight *weight;
  __u32 key;

  c = xdp_ngram_lower(c);

  state->c0 = state->c1;
  state->c1 = state->c2;
  state->c2 = c;

  if (state->seen < XDP_NGRAM_SIZE) {
    state->seen++;
    if (state->seen < XDP_NGRAM_SIZE)
      return;
  }

  key = xdp_ngram_hash3(state->c0, state->c1, state->c2);
  weight = bpf_map_lookup_elem(&xdp_ngram_weights, &key);
  if (!weight)
    return;

  state->coding += weight->coding;
  state->general += weight->general;
  state->reasoning += weight->reasoning;
}

static __always_inline __u32
xdp_ngram_route_for_scores(struct xdp_ngram_state *state) {
  __u32 route = XDP_NGRAM_ROUTE_CODING;
  __s32 best = state->coding;

  if (state->general > best) {
    best = state->general;
    route = XDP_NGRAM_ROUTE_GENERAL;
  }

  if (state->reasoning > best)
    route = XDP_NGRAM_ROUTE_REASONING;

  return route;
}

#endif
