#ifndef XDP_CLASSIFIER_BPF_H
#define XDP_CLASSIFIER_BPF_H

#include "xdp_keyword_classifier.bpf.h"
#include "xdp_ngram_classifier.bpf.h"

#define XDP_ROUTE_CODING 0
#define XDP_ROUTE_GENERAL 1
#define XDP_ROUTE_MATH 2

struct xdp_classifier_state {
#ifdef XDP_CLASSIFIER_LITERAL
  struct xdp_keyword_state keyword;
#else
  struct xdp_ngram_state ngram;
#endif
};

static __always_inline void
xdp_classifier_init(struct xdp_classifier_state *state) {
#ifdef XDP_CLASSIFIER_LITERAL
  xdp_keyword_init(&state->keyword);
#else
  xdp_ngram_init(&state->ngram);
#endif
}

static __always_inline void
xdp_classifier_score_char(struct xdp_classifier_state *state, unsigned char c) {
#ifdef XDP_CLASSIFIER_LITERAL
  xdp_keyword_score_char(&state->keyword, c);
#else
  xdp_ngram_score_char(&state->ngram, c);
#endif
}

static __always_inline __u32
xdp_classifier_route(struct xdp_classifier_state *state) {
#ifdef XDP_CLASSIFIER_LITERAL
  return xdp_keyword_route_for_matches(&state->keyword);
#else
  return xdp_ngram_route_for_scores(&state->ngram);
#endif
}

static __always_inline __u8
xdp_classifier_matched_coding(struct xdp_classifier_state *state) {
#ifdef XDP_CLASSIFIER_LITERAL
  return state->keyword.matched_coding;
#else
  return xdp_ngram_route_for_scores(&state->ngram) == XDP_ROUTE_CODING;
#endif
}

static __always_inline __u8
xdp_classifier_matched_math(struct xdp_classifier_state *state) {
#ifdef XDP_CLASSIFIER_LITERAL
  return state->keyword.matched_math;
#else
  return xdp_ngram_route_for_scores(&state->ngram) == XDP_ROUTE_MATH;
#endif
}

#endif
