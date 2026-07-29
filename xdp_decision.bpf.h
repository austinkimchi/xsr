#ifndef XDP_DECISION_BPF_H
#define XDP_DECISION_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>

#include <bpf/bpf_helpers.h>

#define XDP_MAX_DECISION_RULES 16
#define XDP_MODEL_FALLBACK 0

struct xdp_decision_rule {
  __u64 require_any; // OR: at least one bit must be present. 0 means disabled.
  __u64 require_all; // AND: every bit must be present. 0 means disabled.
  __u64 reject_any;  // NOT: no bits may be present. 0 means disabled.
  __u32 model_id;
  __u32 enabled;
};

struct {
  __uint(type, BPF_MAP_TYPE_ARRAY);
  __uint(max_entries, XDP_MAX_DECISION_RULES);
  __type(key, __u32);
  __type(value, struct xdp_decision_rule);
} xdp_decision_rules SEC(".maps");

static __always_inline int
xdp_decision_rule_matches(const struct xdp_decision_rule *rule, __u64 signals) {
  if (!rule->enabled)
    return 0;

  if (rule->require_any && ((signals & rule->require_any) == 0))
    return 0;

  if ((signals & rule->require_all) != rule->require_all)
    return 0;

  if (signals & rule->reject_any)
    return 0;

  return 1;
}

static __always_inline __u32 xdp_decision_eval(__u64 signals) {
  struct xdp_decision_rule *rule;
  __u32 key;

#define XDP_DECISION_CHECK_RULE(index)                                         \
  key = index;                                                                 \
  rule = bpf_map_lookup_elem(&xdp_decision_rules, &key);                       \
  if (rule && xdp_decision_rule_matches(rule, signals))                        \
  return rule->model_id

  XDP_DECISION_CHECK_RULE(0);
  XDP_DECISION_CHECK_RULE(1);
  XDP_DECISION_CHECK_RULE(2);
  XDP_DECISION_CHECK_RULE(3);
  XDP_DECISION_CHECK_RULE(4);
  XDP_DECISION_CHECK_RULE(5);
  XDP_DECISION_CHECK_RULE(6);
  XDP_DECISION_CHECK_RULE(7);
  XDP_DECISION_CHECK_RULE(8);
  XDP_DECISION_CHECK_RULE(9);
  XDP_DECISION_CHECK_RULE(10);
  XDP_DECISION_CHECK_RULE(11);
  XDP_DECISION_CHECK_RULE(12);
  XDP_DECISION_CHECK_RULE(13);
  XDP_DECISION_CHECK_RULE(14);
  XDP_DECISION_CHECK_RULE(15);

#undef XDP_DECISION_CHECK_RULE

  return XDP_MODEL_FALLBACK;
}

#endif
