#ifndef XDP_KEYWORD_CLASSIFIER_BPF_H
#define XDP_KEYWORD_CLASSIFIER_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>

#include "xdp_router.h"

enum xdp_keyword_route {
  XDP_KEYWORD_ROUTE_CODING = 0,
  XDP_KEYWORD_ROUTE_GENERAL = 1,
  XDP_KEYWORD_ROUTE_MATH = 2,
};

#include "xdp_keyword_policy.generated.h"

struct xdp_keyword_state {
  __u64 signals;
  __u8 matched_coding;
  __u8 matched_math;
  __u8 pos[XDP_KEYWORD_COUNT];
};

static __always_inline unsigned char xdp_keyword_lower(unsigned char c) {
#if XDP_KEYWORD_POLICY_CASE_SENSITIVE
  return c;
#else
  if (c >= 'A' && c <= 'Z')
    return c + ('a' - 'A');
  return c;
#endif
}

static __always_inline void xdp_keyword_mark(struct xdp_keyword_state *state,
                                             __u32 id) {
  if (xdp_keyword_route_for_id(id) == XDP_KEYWORD_ROUTE_CODING)
    state->matched_coding = 1;
  else
    state->matched_math = 1;
}

static __always_inline void xdp_keyword_init(struct xdp_keyword_state *state) {
  state->signals = 0;
  state->matched_coding = 0;
  state->matched_math = 0;

  XDP_KEYWORD_CLEAR_ALL(state);
}

static __always_inline void xdp_keyword_score_one(struct xdp_keyword_state *state,
                                                  __u32 id, unsigned char c) {
  __u8 pos = state->pos[id];
  __u8 len = xdp_keyword_len(id);

  if (!len)
    return;

  if (c == xdp_keyword_char(id, pos)) {
    pos++;
    if (pos == len) {
      xdp_keyword_mark(state, id);
      pos = 0;
    }
  } else {
    pos = c == xdp_keyword_char(id, 0) ? 1 : 0;
  }

  state->pos[id] = pos;
}

static __always_inline void xdp_keyword_score_char(struct xdp_keyword_state *state,
                                                   unsigned char c) {
  c = xdp_keyword_lower(c);

  XDP_KEYWORD_SCORE_ALL(state, c);
}

static __always_inline __u32
xdp_keyword_route_for_matches(struct xdp_keyword_state *state) {
  XDP_KEYWORD_ROUTE_FOR_MATCHES(state);
}

#endif
