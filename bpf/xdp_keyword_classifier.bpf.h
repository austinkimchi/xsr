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

#ifndef MAX_KEYWORDS
#define MAX_KEYWORDS 32
#endif

struct xdp_keyword_state {
  __u64 signals;
  __u8 matched_coding;
  __u8 matched_math;
  __u8 pos[MAX_KEYWORDS];
};

#include "xdp_keyword_policy.generated.h"

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
