#ifndef XDP_JACCARD_CLASSIFIER_BPF_H
#define XDP_JACCARD_CLASSIFIER_BPF_H
#include <linux/bpf.h>
#include <linux/types.h>
#include "../xdp_router.h"
#define XDP_JACCARD_MAX_KEYWORDS 16
#define XDP_JACCARD_MAX_RULES 8
#define XDP_JACCARD_MAX_GRAMS 16
#define XDP_JACCARD_ARITY 3
enum xdp_jaccard_operator { XDP_JACCARD_OR, XDP_JACCARD_AND, XDP_JACCARD_NOR };
struct xdp_jaccard_keyword { __u32 count; __u32 grams[XDP_JACCARD_MAX_GRAMS]; __u8 rule_id; __u8 reserved[3]; };
struct xdp_jaccard_rule { __u32 threshold_milli; __u32 priority; __u8 route; __u8 operator; __u8 arity; __u8 case_sensitive; __u8 keyword_count; __u8 reserved[3]; };
struct xdp_jaccard_policy_config { __u32 keyword_count; __u32 rule_count; };
struct xdp_jaccard_gram_vector { __u64 low; __u64 high; };
struct xdp_jaccard_seen_key { __u64 token; __u32 gram; __u32 reserved; };
#ifdef __BPF__
#include <bpf/bpf_helpers.h>
struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, XDP_JACCARD_MAX_KEYWORDS); __type(key, __u32); __type(value, struct xdp_jaccard_keyword); } xdp_jaccard_keywords SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, XDP_JACCARD_MAX_RULES); __type(key, __u32); __type(value, struct xdp_jaccard_rule); } xdp_jaccard_rules SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, 1); __type(key, __u32); __type(value, struct xdp_jaccard_policy_config); } xdp_jaccard_config SEC(".maps");
/* Exact inverted index: packed gram -> bitset of keywords that contain it. */
struct { __uint(type, BPF_MAP_TYPE_HASH); __uint(max_entries, XDP_JACCARD_MAX_KEYWORDS * XDP_JACCARD_MAX_GRAMS); __type(key, __u32); __type(value, struct xdp_jaccard_gram_vector); } xdp_jaccard_gram_masks SEC(".maps");
struct { __uint(type, BPF_MAP_TYPE_LRU_HASH); __uint(max_entries, 8192); __type(key, struct xdp_jaccard_seen_key); __type(value, __u32); } xdp_jaccard_seen_grams SEC(".maps");
#endif
struct xdp_jaccard_state { __u64 intersections_low, intersections_high, matched_keywords, rule_match_counts, token; __u32 epoch; __u8 gram_count, word_len, first, previous; };
#ifdef __BPF__
static __always_inline unsigned char xdp_jaccard_lower(unsigned char c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }
static __always_inline int xdp_jaccard_word_char(unsigned char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-'; }
static __always_inline __u32 xdp_jaccard_pack3(unsigned char a, unsigned char b, unsigned char c) { return ((__u32)a << 16) | ((__u32)b << 8) | c; }
static __always_inline void xdp_jaccard_reset_word(struct xdp_jaccard_state *s) { s->gram_count = 0; s->word_len = 0; s->first = s->previous = 0; s->intersections_low = 0; s->intersections_high = 0; s->epoch++; if (!s->epoch) s->epoch = 1; }
static __always_inline void xdp_jaccard_add_gram(struct xdp_jaccard_state *s, __u32 gram) {
  struct xdp_jaccard_seen_key seen_key = {.token = s->token, .gram = gram};
  __u32 *seen_epoch = bpf_map_lookup_elem(&xdp_jaccard_seen_grams, &seen_key);
  if (seen_epoch && *seen_epoch == s->epoch) return;
  bpf_map_update_elem(&xdp_jaccard_seen_grams, &seen_key, &s->epoch, BPF_ANY);
  if (s->gram_count >= XDP_JACCARD_MAX_GRAMS) return;
  s->gram_count++;
  struct xdp_jaccard_gram_vector *vector = bpf_map_lookup_elem(&xdp_jaccard_gram_masks, &gram);
  if (!vector) return;
  s->intersections_low += vector->low;
  s->intersections_high += vector->high;
}
struct xdp_jaccard_match_ctx { struct xdp_jaccard_state *state; __u32 keyword_count; };
static long xdp_jaccard_match_keyword_callback(__u32 keyword_id, void *data) {
  struct xdp_jaccard_match_ctx *ctx = data; struct xdp_jaccard_keyword *keyword; struct xdp_jaccard_rule *rule; __u32 key = keyword_id, intersection;
  if (keyword_id >= ctx->keyword_count) return 1;
  keyword = bpf_map_lookup_elem(&xdp_jaccard_keywords, &key); if (!keyword || keyword->rule_id >= XDP_JACCARD_MAX_RULES) return 0;
  key = keyword->rule_id; rule = bpf_map_lookup_elem(&xdp_jaccard_rules, &key); if (!rule || rule->arity != XDP_JACCARD_ARITY || rule->case_sensitive) return 0;
  intersection = keyword_id < 8 ? (ctx->state->intersections_low >> (keyword_id * 5)) & 31 : (ctx->state->intersections_high >> ((keyword_id - 8) * 5)) & 31;
  if (intersection * 1000 >= (ctx->state->gram_count + keyword->count - intersection) * rule->threshold_milli && !(ctx->state->matched_keywords & (1ULL << keyword_id))) { ctx->state->matched_keywords |= 1ULL << keyword_id; ctx->state->rule_match_counts += 1ULL << (keyword->rule_id * 8); }
  return 0;
}
static __always_inline void xdp_jaccard_match_current(struct xdp_jaccard_state *s) { __u32 config_key = 0; struct xdp_jaccard_policy_config *config = bpf_map_lookup_elem(&xdp_jaccard_config, &config_key); struct xdp_jaccard_match_ctx ctx = {}; if (!config) return; ctx.state=s; ctx.keyword_count=config->keyword_count; if(ctx.keyword_count>XDP_JACCARD_MAX_KEYWORDS)ctx.keyword_count=XDP_JACCARD_MAX_KEYWORDS; bpf_loop(XDP_JACCARD_MAX_KEYWORDS,xdp_jaccard_match_keyword_callback,&ctx,0); }
static __always_inline void xdp_jaccard_finish_word(struct xdp_jaccard_state *s) { if (!s->word_len) return; if (s->word_len == 1) xdp_jaccard_add_gram(s, xdp_jaccard_pack3(s->first, ' ', ' ')); else { xdp_jaccard_add_gram(s, xdp_jaccard_pack3(s->previous, s->first, ' ')); xdp_jaccard_add_gram(s, xdp_jaccard_pack3(s->first, ' ', ' ')); } xdp_jaccard_match_current(s); }
static __always_inline void xdp_jaccard_init(struct xdp_jaccard_state *s) { s->matched_keywords = 0; s->rule_match_counts = 0; s->token = ((__u64)bpf_get_prandom_u32() << 32) | bpf_get_prandom_u32(); s->epoch = 0; xdp_jaccard_reset_word(s); }
static __always_inline void xdp_jaccard_score_char(struct xdp_jaccard_state *s, unsigned char c) { if (!xdp_jaccard_word_char(c)) { xdp_jaccard_finish_word(s); xdp_jaccard_reset_word(s); return; } c=xdp_jaccard_lower(c); if (!s->word_len) {s->first=s->previous=c;s->word_len=1;xdp_jaccard_add_gram(s,xdp_jaccard_pack3(' ',' ',c));} else if(s->word_len==1){xdp_jaccard_add_gram(s,xdp_jaccard_pack3(' ',s->first,c));s->previous=s->first;s->first=c;s->word_len++;}else{xdp_jaccard_add_gram(s,xdp_jaccard_pack3(s->previous,s->first,c));s->previous=s->first;s->first=c;s->word_len++;} }
static __always_inline __u32 xdp_jaccard_route(struct xdp_jaccard_state *s) { __u32 config_key=0,best_route=XDP_ROUTE_GENERAL,best_priority=0; struct xdp_jaccard_policy_config *config=bpf_map_lookup_elem(&xdp_jaccard_config,&config_key); if(!config)return best_route;
#pragma clang loop unroll(disable)
  for(int i=0;i<XDP_JACCARD_MAX_RULES;i++){__u32 key=i,matched=(s->rule_match_counts>>(i*8))&255;struct xdp_jaccard_rule *rule;if((__u32)i>=config->rule_count)break;rule=bpf_map_lookup_elem(&xdp_jaccard_rules,&key);if(!rule)continue; if((rule->operator==XDP_JACCARD_OR?matched>0:rule->operator==XDP_JACCARD_AND?matched==rule->keyword_count:rule->operator==XDP_JACCARD_NOR?matched==0:0)&&rule->priority>=best_priority){best_priority=rule->priority;best_route=rule->route;}}return best_route; }
static __always_inline __u8 xdp_jaccard_rule_matches(struct xdp_jaccard_state *s,__u32 route){return xdp_jaccard_route(s)==route;}
#endif
#endif
