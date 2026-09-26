#ifndef XDP_BM25_CLASSIFIER_BPF_H
#define XDP_BM25_CLASSIFIER_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>
#include "xsr/router.h"
#include "../parsing/xdp_datapath_limits.h"

#define XDP_BM25_MAX_RULES 8
#define XDP_BM25_MAX_DOCUMENTS 16
#define XDP_BM25_MAX_TERMS 2048
#define XDP_BM25_MAX_TOKEN_BYTES 64
/* One-byte ASCII tokens need at least one delimiter byte between them.  This
 * is the maximum possible token count in the largest request the stream
 * datapath accepts; the packet datapath has a smaller byte bound. */
#define XDP_BM25_MAX_QUERY_TOKENS \
  ((XDP_MAX_STREAM_REQUEST_BYTES + 1U) / 2U)

enum xdp_bm25_operator { XDP_BM25_OR, XDP_BM25_AND, XDP_BM25_NOR };

struct xdp_bm25_rule {
  __s64 threshold_fixed;
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
  __s64 thresholds_fixed[XDP_BM25_MAX_DOCUMENTS];
};

struct xdp_bm25_term_weights {
  __s64 weights[XDP_BM25_MAX_DOCUMENTS];
  __u8 token[XDP_BM25_MAX_TOKEN_BYTES];
  __u8 token_length;
  __u8 stopword;
};

#ifdef __BPF__
#include <bpf/bpf_helpers.h>
struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, XDP_BM25_MAX_RULES); __type(key, __u32); __type(value, struct xdp_bm25_rule); } xdp_bm25_rules SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, 1); __type(key, __u32); __type(value, struct xdp_bm25_policy_config); } xdp_bm25_config SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_HASH); __uint(max_entries, XDP_BM25_MAX_TERMS); __type(key, __u32); __type(value, struct xdp_bm25_term_weights); } xdp_bm25_terms SEC(".maps");
#endif

struct xdp_bm25_state {
  __s64 scores[XDP_BM25_MAX_DOCUMENTS];
  __u32 hash;
  __u32 query_tokens;
  __u16 matched_documents;
  __u8 token_length;
  __u8 in_word;
  __u8 pending_connector;
  __u8 previous_char;
  __u8 overflow;
  __u8 token_overflow;
  __u8 token[XDP_BM25_MAX_TOKEN_BYTES];
};

#ifdef __BPF__
static __always_inline int xdp_bm25_word_char(unsigned char c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
         (c >= '0' && c <= '9');
}

static __always_inline int xdp_bm25_connector(unsigned char c) {
  return c == '\'' || c == '.' || c == '_';
}

static __always_inline unsigned char xdp_bm25_lower(unsigned char c) {
  return c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c;
}

struct xdp_bm25_add_ctx {
  struct xdp_bm25_state *state;
  const struct xdp_bm25_term_weights *term;
};

struct xdp_bm25_match_ctx {
  const struct xdp_bm25_state *state;
  const struct xdp_bm25_term_weights *term;
  __u8 matches;
};

static long xdp_bm25_match_callback(__u32 position, void *data) {
  struct xdp_bm25_match_ctx *ctx = data;
  __u32 index = position & (XDP_BM25_MAX_TOKEN_BYTES - 1);

  if (position >= ctx->state->token_length)
    return 1;
  if (ctx->state->token[index] != ctx->term->token[index]) {
    ctx->matches = 0;
    return 1;
  }
  return 0;
}

static __always_inline int
xdp_bm25_token_matches(const struct xdp_bm25_state *state,
                       const struct xdp_bm25_term_weights *term) {
  struct xdp_bm25_match_ctx ctx = {
      .state = state,
      .term = term,
      .matches = 1,
  };

  if (state->token_overflow || state->token_length != term->token_length)
    return 0;
  bpf_loop(XDP_BM25_MAX_TOKEN_BYTES, xdp_bm25_match_callback, &ctx, 0);
  return ctx.matches;
}

static __always_inline void
xdp_bm25_append_token_byte(struct xdp_bm25_state *state, unsigned char c) {
  if (state->token_length < XDP_BM25_MAX_TOKEN_BYTES) {
    __u32 index = state->token_length & (XDP_BM25_MAX_TOKEN_BYTES - 1);
    state->token[index] = c;
    state->token_length++;
  } else {
    state->token_overflow = 1;
  }
}

static long xdp_bm25_add_callback(__u32 document, void *data) {
  struct xdp_bm25_add_ctx *ctx = data;
  __u32 index = document & (XDP_BM25_MAX_DOCUMENTS - 1);
  __u32 config_key = 0;
  __s64 weight = ctx->term->weights[index];
  struct xdp_bm25_policy_config *config;
  if (!weight)
    return 0;
  ctx->state->scores[index] += weight;
  config = bpf_map_lookup_elem(&xdp_bm25_config, &config_key);
  if (config && ctx->state->scores[index] >= config->thresholds_fixed[index])
    ctx->state->matched_documents |= 1U << index;
  return 0;
}

static __noinline void xdp_bm25_finish_word(struct xdp_bm25_state *state) {
  struct xdp_bm25_term_weights *term;
  struct xdp_bm25_add_ctx ctx = {};
  int exact_match;

  if (!state->in_word)
    return;
  state->pending_connector = 0;

  /* VSR removes stop words before stemming.  Stop-word hashes are generated
   * into the same read-only policy map with zero document weights. */
  term = bpf_map_lookup_elem(&xdp_bm25_terms, &state->hash);
  exact_match = term && xdp_bm25_token_matches(state, term);
  if (exact_match && term->stopword)
    goto reset;
  if (state->query_tokens >= XDP_BM25_MAX_QUERY_TOKENS) {
    state->overflow = 1;
    goto reset;
  }
  state->query_tokens++;
  /* Corpus stems and their generator-proven surface aliases share a vector. */
  if (exact_match && !term->stopword) {
    ctx.state = state;
    ctx.term = term;
    bpf_loop(XDP_BM25_MAX_DOCUMENTS, xdp_bm25_add_callback, &ctx, 0);
  }
reset:
  state->hash = 2166136261U;
  state->in_word = 0;
  state->pending_connector = 0;
  state->previous_char = 0;
  state->token_length = 0;
  state->token_overflow = 0;
}

static __noinline void xdp_bm25_init(struct xdp_bm25_state *state) {
  __builtin_memset(state, 0, sizeof(*state));
  state->hash = 2166136261U;
}

static __noinline void xdp_bm25_score_char(struct xdp_bm25_state *state,
                                            unsigned char c) {
  c = xdp_bm25_lower(c);
  if (xdp_bm25_word_char(c)) {
    if (state->pending_connector) {
      int valid = state->pending_connector != '.' ||
                  ((state->previous_char >= '0' && state->previous_char <= '9') &&
                   (c >= '0' && c <= '9'));
      if (valid) {
        state->hash = (state->hash ^ state->pending_connector) * 16777619U;
        xdp_bm25_append_token_byte(state, state->pending_connector);
      } else {
        xdp_bm25_finish_word(state);
      }
      state->pending_connector = 0;
    }
    state->hash = (state->hash ^ c) * 16777619U;
    xdp_bm25_append_token_byte(state, c);
    state->in_word = 1;
    state->previous_char = c;
    return;
  }
  if (xdp_bm25_connector(c) && state->in_word && !state->pending_connector) {
    state->pending_connector = c;
    return;
  }
  if (state->in_word)
    xdp_bm25_finish_word(state);
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
