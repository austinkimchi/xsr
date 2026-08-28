#ifndef XDP_CLASSIFIER_BPF_H
#define XDP_CLASSIFIER_BPF_H

#include "xdp_jaccard_classifier.bpf.h"

struct xdp_classifier_state {
  struct xdp_jaccard_state jaccard;
};

static __always_inline void xdp_classifier_init(struct xdp_classifier_state *state) {
  xdp_jaccard_init(&state->jaccard);
}

static __always_inline void xdp_classifier_score_char(struct xdp_classifier_state *state,
                                                       unsigned char c) {
  xdp_jaccard_score_char(&state->jaccard, c);
}

static __always_inline void xdp_classifier_finish(struct xdp_classifier_state *state) {
  xdp_jaccard_finish(&state->jaccard);
}

static __always_inline __u32 xdp_classifier_route(struct xdp_classifier_state *state) {
  return xdp_jaccard_route(&state->jaccard);
}

static __always_inline __u8 xdp_classifier_matched_coding(struct xdp_classifier_state *state) {
  return xdp_jaccard_rule_matches(&state->jaccard, XDP_ROUTE_CODING);
}

static __always_inline __u8 xdp_classifier_matched_math(struct xdp_classifier_state *state) {
  return xdp_jaccard_rule_matches(&state->jaccard, XDP_ROUTE_MATH);
}

static __always_inline __u8 xdp_classifier_matched_qa(struct xdp_classifier_state *state) {
  return xdp_jaccard_rule_matches(&state->jaccard, XDP_ROUTE_QA);
}

static __always_inline __u8 xdp_classifier_matched_writing(struct xdp_classifier_state *state) {
  return xdp_jaccard_rule_matches(&state->jaccard, XDP_ROUTE_WRITING);
}

#endif
