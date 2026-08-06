#ifndef XDP_CLASSIFIER_BPF_H
#define XDP_CLASSIFIER_BPF_H

#include "xdp_ngram_classifier.bpf.h"

struct xdp_classifier_state {
  struct xdp_ngram_state ngram;
};

static __always_inline void
xdp_classifier_init(struct xdp_classifier_state *state) {
  xdp_ngram_init(&state->ngram);
}

static __always_inline void
xdp_classifier_score_char(struct xdp_classifier_state *state, unsigned char c) {
  xdp_ngram_score_char(&state->ngram, c);
}

static __always_inline __u32
xdp_classifier_route(struct xdp_classifier_state *state) {
  return xdp_ngram_route_for_scores(&state->ngram);
}

static __always_inline __u8
xdp_classifier_matched_coding(struct xdp_classifier_state *state) {
  return xdp_ngram_route_for_scores(&state->ngram) == XDP_ROUTE_CODING;
}

static __always_inline __u8
xdp_classifier_matched_math(struct xdp_classifier_state *state) {
  return xdp_ngram_route_for_scores(&state->ngram) == XDP_ROUTE_MATH;
}

#endif
