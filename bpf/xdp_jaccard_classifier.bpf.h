#ifndef XDP_JACCARD_CLASSIFIER_BPF_H
#define XDP_JACCARD_CLASSIFIER_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>
#include "../xdp_router.h"

/* Fixed bounds keep both policy data and streaming searches verifier-safe. */
#define XDP_JACCARD_MAX_KEYWORDS 16
#define XDP_JACCARD_MAX_RULES 8
#define XDP_JACCARD_MAX_GRAMS 32
#define XDP_JACCARD_MAX_TEXT_GRAMS 128
#define XDP_JACCARD_ARITY 3
#define XDP_JACCARD_INTERSECTION_BITS 6

enum xdp_jaccard_operator { XDP_JACCARD_OR, XDP_JACCARD_AND, XDP_JACCARD_NOR };

/* Three Unicode scalar values preserve ngrammatic's character (not UTF-8 byte)
 * semantics without accepting hash collisions. */
struct xdp_jaccard_gram { __u32 a; __u32 b; __u32 c; };
struct xdp_jaccard_keyword {
  __u32 count;
  __u32 total_grams;
  struct xdp_jaccard_gram grams[XDP_JACCARD_MAX_GRAMS];
  __u8 gram_counts[XDP_JACCARD_MAX_GRAMS];
  __u8 rule_id;
  __u8 reserved[3];
};
struct xdp_jaccard_rule {
  __u32 threshold_milli;
  __u32 priority;
  __u8 route;
  __u8 operator;
  __u8 arity;
  __u8 case_sensitive;
  __u8 keyword_count;
  __u8 reserved[3];
};
struct xdp_jaccard_policy_config {
  __u32 keyword_count;
  __u32 rule_count;
  __u8 case_sensitive;
  __u8 reserved[3];
};
struct xdp_jaccard_query_key { __u64 token; struct xdp_jaccard_gram gram; };
struct xdp_jaccard_gram_key { struct xdp_jaccard_gram gram; __u8 occurrence; __u8 reserved[3]; };
struct xdp_jaccard_gram_vector { __u64 low; __u64 high; };
struct xdp_jaccard_casefold { __u32 from; __u32 to; };

#ifdef __BPF__
#include <bpf/bpf_helpers.h>
#include "xdp_unicode_word.generated.h"
struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, XDP_JACCARD_MAX_KEYWORDS); __type(key, __u32); __type(value, struct xdp_jaccard_keyword); } xdp_jaccard_keywords SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, XDP_JACCARD_MAX_RULES); __type(key, __u32); __type(value, struct xdp_jaccard_rule); } xdp_jaccard_rules SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, 1); __type(key, __u32); __type(value, struct xdp_jaccard_policy_config); } xdp_jaccard_config SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_LRU_HASH); __uint(max_entries, 8192); __type(key, struct xdp_jaccard_query_key); __type(value, __u8); } xdp_jaccard_query_grams SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_HASH); __uint(max_entries, XDP_JACCARD_MAX_KEYWORDS * XDP_JACCARD_MAX_GRAMS); __type(key, struct xdp_jaccard_gram_key); __type(value, struct xdp_jaccard_gram_vector); } xdp_jaccard_gram_masks SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_HASH); __uint(max_entries, 128); __type(key, __u32); __type(value, __u32); } xdp_jaccard_casefolds SEC(".maps");
#endif

struct xdp_jaccard_query {
  __u64 token;
  __u64 intersections_low;
  __u64 intersections_high;
  __u16 total;
  __u8 overflow;
  __u8 reserved;
};

struct xdp_jaccard_state {
  __u64 matched_keywords;
  __u64 rule_match_counts;
  struct xdp_jaccard_query word;
  struct xdp_jaccard_query full;
  __u32 word_previous;
  __u32 word_last;
  __u32 full_previous;
  __u32 full_last;
  __u32 utf8_value;
  __u32 utf8_min;
  __u16 word_len;
  __u16 full_len;
  __u8 utf8_remaining;
  __u8 case_sensitive;
  __u8 reserved[2];
};

#ifdef __BPF__
static __always_inline struct xdp_jaccard_gram xdp_jaccard_gram3(__u32 a, __u32 b, __u32 c) {
  return (struct xdp_jaccard_gram){.a = a, .b = b, .c = c};
}

static __always_inline __u32 xdp_jaccard_lower(__u32 c) {
  __u32 *mapped;
  if (c >= 'A' && c <= 'Z')
    return c + 32;
  mapped = bpf_map_lookup_elem(&xdp_jaccard_casefolds, &c);
  return mapped ? *mapped : c;
}

static __always_inline int xdp_jaccard_word_char(__u32 c) {
  __u32 word;
  if (c < 128)
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '_' || c == '-';
  if (c > XDP_UNICODE_WORD_MAX)
    return 0;
  word = c >> 6;
  asm volatile("" : "+r"(word));
  if (word >= XDP_UNICODE_WORD_BITMAP_WORDS)
    return 0;
  return (xdp_unicode_word_bitmap[word] >> (c & 63)) & 1;
}

static __noinline void xdp_jaccard_reset_query(struct xdp_jaccard_query *q) {
  q->token = ((__u64)bpf_get_prandom_u32() << 32) | bpf_get_prandom_u32();
  q->total = 0;
  q->intersections_low = 0;
  q->intersections_high = 0;
  q->overflow = 0;
}

static __noinline void xdp_jaccard_add_gram(struct xdp_jaccard_query *q,
                                            struct xdp_jaccard_gram gram,
                                            __u16 limit) {
  struct xdp_jaccard_query_key key = {.token = q->token, .gram = gram};
  struct xdp_jaccard_gram_key mask_key = {.gram = gram};
  struct xdp_jaccard_gram_vector *vector;
  __u8 *count;
  __u8 next;
  if (q->total >= limit) {
    q->overflow = 1;
    return;
  }
  count = bpf_map_lookup_elem(&xdp_jaccard_query_grams, &key);
  next = count && *count < 255 ? *count + 1 : 1;
  bpf_map_update_elem(&xdp_jaccard_query_grams, &key, &next, BPF_ANY);
  mask_key.occurrence = next;
  vector = bpf_map_lookup_elem(&xdp_jaccard_gram_masks, &mask_key);
  if (vector) {
    q->intersections_low += vector->low;
    q->intersections_high += vector->high;
  }
  q->total++;
}

struct xdp_jaccard_match_ctx { struct xdp_jaccard_state *state; struct xdp_jaccard_query *query; __u32 keyword_count; };
static long xdp_jaccard_match_keyword_callback(__u32 keyword_id, void *data) {
  struct xdp_jaccard_match_ctx *ctx = data;
  struct xdp_jaccard_keyword *keyword;
  struct xdp_jaccard_rule *rule;
  __u32 key = keyword_id, same = 0, all, diff;

  if (keyword_id >= ctx->keyword_count || ctx->query->overflow)
    return 1;
  keyword = bpf_map_lookup_elem(&xdp_jaccard_keywords, &key);
  if (!keyword || keyword->rule_id >= XDP_JACCARD_MAX_RULES)
    return 0;
  key = keyword->rule_id;
  rule = bpf_map_lookup_elem(&xdp_jaccard_rules, &key);
  if (!rule || rule->arity != XDP_JACCARD_ARITY)
    return 0;
  same = keyword_id < 8 ?
      (ctx->query->intersections_low >> (keyword_id * XDP_JACCARD_INTERSECTION_BITS)) & 63 :
      (ctx->query->intersections_high >> ((keyword_id - 8) * XDP_JACCARD_INTERSECTION_BITS)) & 63;
  if (!same || !ctx->query->total || !keyword->total_grams)
    return 0;
  all = ctx->query->total + keyword->total_grams - same;
  diff = all - same;
  if ((all * all - diff * diff) * 1000 >= all * all * rule->threshold_milli &&
      !(ctx->state->matched_keywords & (1ULL << keyword_id))) {
    ctx->state->matched_keywords |= 1ULL << keyword_id;
    ctx->state->rule_match_counts += 1ULL << (keyword->rule_id * 8);
  }
  return 0;
}

static __noinline void xdp_jaccard_match_query(struct xdp_jaccard_state *s,
                                               struct xdp_jaccard_query *q) {
  __u32 config_key = 0;
  struct xdp_jaccard_policy_config *config = bpf_map_lookup_elem(&xdp_jaccard_config, &config_key);
  struct xdp_jaccard_match_ctx ctx = {.state = s, .query = q};
  if (!config || q->overflow)
    return;
  ctx.keyword_count = config->keyword_count;
  if (ctx.keyword_count > XDP_JACCARD_MAX_KEYWORDS)
    ctx.keyword_count = XDP_JACCARD_MAX_KEYWORDS;
  bpf_loop(XDP_JACCARD_MAX_KEYWORDS, xdp_jaccard_match_keyword_callback, &ctx, 0);
}

static __noinline void xdp_jaccard_finish_word(struct xdp_jaccard_state *s) {
  if (!s->word_len)
    return;
  if (s->word_len == 1)
    xdp_jaccard_add_gram(&s->word, xdp_jaccard_gram3(s->word_last, ' ', ' '), XDP_JACCARD_MAX_GRAMS);
  else {
    xdp_jaccard_add_gram(&s->word, xdp_jaccard_gram3(s->word_previous, s->word_last, ' '), XDP_JACCARD_MAX_GRAMS);
    xdp_jaccard_add_gram(&s->word, xdp_jaccard_gram3(s->word_last, ' ', ' '), XDP_JACCARD_MAX_GRAMS);
  }
  xdp_jaccard_match_query(s, &s->word);
}

static __always_inline void xdp_jaccard_push(struct xdp_jaccard_query *q,
                                             __u32 *previous, __u32 *last,
                                             __u16 *length, __u32 c,
                                             __u16 limit) {
  if (!*length) {
    *last = c;
    *length = 1;
    xdp_jaccard_add_gram(q, xdp_jaccard_gram3(' ', ' ', c), limit);
  } else if (*length == 1) {
    xdp_jaccard_add_gram(q, xdp_jaccard_gram3(' ', *last, c), limit);
    *previous = *last;
    *last = c;
    (*length)++;
  } else {
    xdp_jaccard_add_gram(q, xdp_jaccard_gram3(*previous, *last, c), limit);
    *previous = *last;
    *last = c;
    if (*length < 65535)
      (*length)++;
  }
}

static __noinline void xdp_jaccard_init(struct xdp_jaccard_state *s) {
  __u32 key = 0;
  struct xdp_jaccard_policy_config *config;
  __builtin_memset(s, 0, sizeof(*s));
  config = bpf_map_lookup_elem(&xdp_jaccard_config, &key);
  if (config)
    s->case_sensitive = config->case_sensitive;
  xdp_jaccard_reset_query(&s->word);
  xdp_jaccard_reset_query(&s->full);
}

static __noinline void xdp_jaccard_score_codepoint(struct xdp_jaccard_state *s, __u32 c) {
  if (!s->case_sensitive)
    c = xdp_jaccard_lower(c);
  xdp_jaccard_push(&s->full, &s->full_previous, &s->full_last,
                   &s->full_len, c, XDP_JACCARD_MAX_TEXT_GRAMS);
  if (!xdp_jaccard_word_char(c)) {
    xdp_jaccard_finish_word(s);
    xdp_jaccard_reset_query(&s->word);
    s->word_len = 0;
    return;
  }
  xdp_jaccard_push(&s->word, &s->word_previous, &s->word_last,
                   &s->word_len, c, XDP_JACCARD_MAX_GRAMS);
}

static __noinline void xdp_jaccard_score_char(struct xdp_jaccard_state *s, unsigned char byte) {
  __u32 c;
  if (!s->utf8_remaining) {
    if (byte < 0x80) {
      xdp_jaccard_score_codepoint(s, byte);
      return;
    }
    if ((byte & 0xe0) == 0xc0) { s->utf8_value = byte & 0x1f; s->utf8_min = 0x80; s->utf8_remaining = 1; return; }
    if ((byte & 0xf0) == 0xe0) { s->utf8_value = byte & 0x0f; s->utf8_min = 0x800; s->utf8_remaining = 2; return; }
    if ((byte & 0xf8) == 0xf0) { s->utf8_value = byte & 0x07; s->utf8_min = 0x10000; s->utf8_remaining = 3; return; }
    xdp_jaccard_score_codepoint(s, ' ');
    return;
  }
  if ((byte & 0xc0) != 0x80) {
    s->utf8_remaining = 0;
    s->utf8_value = 0;
    xdp_jaccard_score_codepoint(s, ' ');
    if (byte < 0x80)
      xdp_jaccard_score_codepoint(s, byte);
    return;
  }
  s->utf8_value = (s->utf8_value << 6) | (byte & 0x3f);
  if (--s->utf8_remaining)
    return;
  c = s->utf8_value;
  s->utf8_value = 0;
  if (c < s->utf8_min || c > 0x10ffff || (c >= 0xd800 && c <= 0xdfff))
    c = ' ';
  xdp_jaccard_score_codepoint(s, c);
}

static __noinline void xdp_jaccard_finish(struct xdp_jaccard_state *s) {
  if (s->utf8_remaining) {
    s->utf8_remaining = 0;
    xdp_jaccard_score_codepoint(s, ' ');
  }
  xdp_jaccard_finish_word(s);
  if (!s->full_len)
    return;
  if (s->full_len == 1)
    xdp_jaccard_add_gram(&s->full, xdp_jaccard_gram3(s->full_last, ' ', ' '), XDP_JACCARD_MAX_TEXT_GRAMS);
  else {
    xdp_jaccard_add_gram(&s->full, xdp_jaccard_gram3(s->full_previous, s->full_last, ' '), XDP_JACCARD_MAX_TEXT_GRAMS);
    xdp_jaccard_add_gram(&s->full, xdp_jaccard_gram3(s->full_last, ' ', ' '), XDP_JACCARD_MAX_TEXT_GRAMS);
  }
  xdp_jaccard_match_query(s, &s->full);
}

static __noinline __u32 xdp_jaccard_route_priority(struct xdp_jaccard_state *s,
                                                   __u32 *priority) {
  __u32 config_key = 0, best_route = XDP_ROUTE_GENERAL, best_priority = 0;
  struct xdp_jaccard_policy_config *config = bpf_map_lookup_elem(&xdp_jaccard_config, &config_key);
  if (!config)
    goto out;
#pragma clang loop unroll(disable)
  for (int i = 0; i < XDP_JACCARD_MAX_RULES; i++) {
    __u32 key = i, matched = (s->rule_match_counts >> (i * 8)) & 255;
    struct xdp_jaccard_rule *rule;
    if ((__u32)i >= config->rule_count)
      break;
    rule = bpf_map_lookup_elem(&xdp_jaccard_rules, &key);
    if (!rule)
      continue;
    if ((rule->operator == XDP_JACCARD_OR ? matched > 0 :
         rule->operator == XDP_JACCARD_AND ? matched == rule->keyword_count :
         rule->operator == XDP_JACCARD_NOR ? matched == 0 : 0) && rule->priority >= best_priority) {
      best_priority = rule->priority;
      best_route = rule->route;
    }
  }
out:
  *priority = best_priority;
  return best_route;
}
static __noinline __u32 xdp_jaccard_route(struct xdp_jaccard_state *s) {
  __u32 priority = 0;
  return xdp_jaccard_route_priority(s, &priority);
}
static __noinline __u8 xdp_jaccard_rule_matches(struct xdp_jaccard_state *s, __u32 route) { return xdp_jaccard_route(s) == route; }
#endif
#endif
