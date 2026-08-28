#ifndef XDP_CLASSIFIER_BPF_H
#define XDP_CLASSIFIER_BPF_H

#include "xdp_keyword_modules.generated.h"
#if XDP_KEYWORD_ENABLE_NGRAM
#include "xdp_ngram_classifier.bpf.h"
#endif
#if XDP_KEYWORD_ENABLE_BM25
#include "xdp_bm25_classifier.bpf.h"
#endif

struct xdp_classifier_state {
#if XDP_KEYWORD_ENABLE_NGRAM
  struct xdp_jaccard_state jaccard;
#endif
#if XDP_KEYWORD_ENABLE_BM25
  struct xdp_bm25_state bm25;
#endif
};

static __always_inline void xdp_classifier_init(struct xdp_classifier_state *state) {
#if XDP_KEYWORD_ENABLE_NGRAM
  xdp_jaccard_init(&state->jaccard);
#endif
#if XDP_KEYWORD_ENABLE_BM25
  xdp_bm25_init(&state->bm25);
#endif
}

static __always_inline void xdp_classifier_score_char(struct xdp_classifier_state *state,
                                                       unsigned char c) {
#if XDP_KEYWORD_ENABLE_NGRAM
  xdp_jaccard_score_char(&state->jaccard, c);
#endif
#if XDP_KEYWORD_ENABLE_BM25
  xdp_bm25_score_char(&state->bm25, c);
#endif
}

static __always_inline void xdp_classifier_finish(struct xdp_classifier_state *state) {
#if XDP_KEYWORD_ENABLE_NGRAM
  xdp_jaccard_finish_word(&state->jaccard);
#endif
#if XDP_KEYWORD_ENABLE_BM25
  xdp_bm25_finish_word(&state->bm25);
#endif
}

static __always_inline __u32 xdp_classifier_route(struct xdp_classifier_state *state) {
  __u32 route = XDP_ROUTE_GENERAL, priority = 0;
#if XDP_KEYWORD_ENABLE_NGRAM
  route = xdp_jaccard_route_priority(&state->jaccard, &priority);
#endif
#if XDP_KEYWORD_ENABLE_BM25
  __u32 bm25_priority = 0;
  __u32 bm25_route = xdp_bm25_route_priority(&state->bm25, &bm25_priority);
  if (bm25_route != XDP_ROUTE_GENERAL && bm25_priority >= priority) {
    route = bm25_route;
    priority = bm25_priority;
  }
#endif
  return route;
}

static __always_inline __u8 xdp_classifier_matched_coding(struct xdp_classifier_state *state) {
  return xdp_classifier_route(state) == XDP_ROUTE_CODING;
}

static __always_inline __u8 xdp_classifier_matched_math(struct xdp_classifier_state *state) {
  return xdp_classifier_route(state) == XDP_ROUTE_MATH;
}

static __always_inline __u8 xdp_classifier_matched_qa(struct xdp_classifier_state *state) {
  return xdp_classifier_route(state) == XDP_ROUTE_QA;
}

static __always_inline __u8 xdp_classifier_matched_writing(struct xdp_classifier_state *state) {
  return xdp_classifier_route(state) == XDP_ROUTE_WRITING;
}

#endif
