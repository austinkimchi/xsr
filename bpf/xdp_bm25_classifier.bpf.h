#ifndef XDP_BM25_CLASSIFIER_BPF_H
#define XDP_BM25_CLASSIFIER_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>
#include "../xdp_router.h"

#define XDP_BM25_MAX_RULES 8
#define XDP_BM25_MAX_DOCUMENTS 16
#define XDP_BM25_MAX_TERMS 128
#define XDP_BM25_MAX_TOKEN_LEN 32
#define XDP_BM25_MAX_QUERY_TOKENS 256

enum xdp_bm25_operator { XDP_BM25_OR, XDP_BM25_AND, XDP_BM25_NOR };

struct xdp_bm25_rule {
  __u32 threshold_micro;
  __u32 priority;
  __u8 route;
  __u8 operator;
  __u8 document_start;
  __u8 document_count;
  __u16 document_mask;
};

struct xdp_bm25_policy_config {
  __u32 rule_count;
  __u32 document_count;
  __u32 thresholds_micro[XDP_BM25_MAX_DOCUMENTS];
};

struct xdp_bm25_term_weights { __u32 weights[XDP_BM25_MAX_DOCUMENTS]; };

#ifdef __BPF__
#include <bpf/bpf_helpers.h>
struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, XDP_BM25_MAX_RULES); __type(key, __u32); __type(value, struct xdp_bm25_rule); } xdp_bm25_rules SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, 1); __type(key, __u32); __type(value, struct xdp_bm25_policy_config); } xdp_bm25_config SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_HASH); __uint(max_entries, XDP_BM25_MAX_TERMS); __type(key, __u32); __type(value, struct xdp_bm25_term_weights); } xdp_bm25_terms SEC(".maps");
#endif

struct xdp_bm25_state {
  __u64 scores[XDP_BM25_MAX_DOCUMENTS];
  __u32 hash;
  __u16 query_tokens;
  __u16 matched_documents;
  __u8 word_len;
  __u8 word_overflow;
  __u8 overflow;
};

#ifdef __BPF__
static __always_inline int xdp_bm25_word_char(unsigned char c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
         (c >= '0' && c <= '9');
}

static __always_inline unsigned char xdp_bm25_lower(unsigned char c) {
  return c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c;
}

struct xdp_bm25_add_ctx {
  struct xdp_bm25_state *state;
  const struct xdp_bm25_term_weights *term;
};

static long xdp_bm25_add_callback(__u32 document, void *data) {
  struct xdp_bm25_add_ctx *ctx = data;
  __u32 index = document & (XDP_BM25_MAX_DOCUMENTS - 1);
  __u32 config_key = 0, weight = ctx->term->weights[index];
  struct xdp_bm25_policy_config *config;
  if (!weight)
    return 0;
  ctx->state->scores[index] += weight;
  config = bpf_map_lookup_elem(&xdp_bm25_config, &config_key);
  if (config && ctx->state->scores[index] >= config->thresholds_micro[index])
    ctx->state->matched_documents |= 1U << index;
  return 0;
}

static __noinline void xdp_bm25_finish_word(struct xdp_bm25_state *state) {
  struct xdp_bm25_term_weights *term;
  struct xdp_bm25_add_ctx ctx = {};

  if (!state->word_len)
    return;
  if (state->query_tokens >= XDP_BM25_MAX_QUERY_TOKENS) {
    state->overflow = 1;
    goto reset;
  }
  state->query_tokens++;
  if (state->word_overflow)
    goto reset;
  term = bpf_map_lookup_elem(&xdp_bm25_terms, &state->hash);
  if (term) {
    ctx.state = state;
    ctx.term = term;
    bpf_loop(XDP_BM25_MAX_DOCUMENTS, xdp_bm25_add_callback, &ctx, 0);
  }
reset:
  state->hash = 2166136261U;
  state->word_len = 0;
  state->word_overflow = 0;
}

static __noinline void xdp_bm25_init(struct xdp_bm25_state *state) {
  __builtin_memset(state, 0, sizeof(*state));
  state->hash = 2166136261U;
}

static __noinline void xdp_bm25_score_char(struct xdp_bm25_state *state,
                                            unsigned char c) {
  if (!xdp_bm25_word_char(c)) {
    xdp_bm25_finish_word(state);
    return;
  }
  if (state->word_len >= XDP_BM25_MAX_TOKEN_LEN) {
    state->word_overflow = 1;
    return;
  }
  c = xdp_bm25_lower(c);
  state->hash = (state->hash ^ c) * 16777619U;
  state->word_len++;
}

static __noinline __u32
xdp_bm25_route_priority(struct xdp_bm25_state *state, __u32 *priority) {
  __u32 config_key = 0, best_route = XDP_ROUTE_GENERAL, best_priority = 0;
  struct xdp_bm25_policy_config *config =
      bpf_map_lookup_elem(&xdp_bm25_config, &config_key);
  if (!config || state->overflow)
    goto out;
#pragma clang loop unroll(disable)
  for (int i = 0; i < XDP_BM25_MAX_RULES; i++) {
    __u32 key = i;
    struct xdp_bm25_rule *rule;
    __u16 matched;
    if ((__u32)i >= config->rule_count)
      break;
    rule = bpf_map_lookup_elem(&xdp_bm25_rules, &key);
    if (!rule)
      continue;
    if (rule->document_start >= XDP_BM25_MAX_DOCUMENTS ||
        rule->document_count > XDP_BM25_MAX_DOCUMENTS - rule->document_start)
      continue;
    matched = state->matched_documents & rule->document_mask;
    if ((rule->operator == XDP_BM25_OR ? matched != 0 :
         rule->operator == XDP_BM25_AND ? matched == rule->document_mask :
         rule->operator == XDP_BM25_NOR ? matched == 0 : 0) &&
        rule->priority >= best_priority) {
      best_priority = rule->priority;
      best_route = rule->route;
    }
  }
out:
  *priority = best_priority;
  return best_route;
}

static __noinline __u32 xdp_bm25_route(struct xdp_bm25_state *state) {
  __u32 priority = 0;
  return xdp_bm25_route_priority(state, &priority);
}
#endif
#endif
