#ifndef XDP_KEYWORD_POLICY_LOADER_H
#define XDP_KEYWORD_POLICY_LOADER_H

#if XDP_KEYWORD_ENABLE_BM25
static int populate_bm25_policy(struct bpf_object *obj) {
  int config_fd = bpf_object__find_map_fd_by_name(obj, "xdp_bm25_config");
  int rules_fd = bpf_object__find_map_fd_by_name(obj, "xdp_bm25_rules");
  int terms_fd = bpf_object__find_map_fd_by_name(obj, "xdp_bm25_terms");
  __u32 key = 0;

  if (config_fd < 0 || rules_fd < 0 || terms_fd < 0)
    return -1;
  if (bpf_map_update_elem(config_fd, &key, &xdp_bm25_generated_config,
                          BPF_ANY) != 0)
    return -1;
  for (key = 0; key < XDP_BM25_GENERATED_RULE_COUNT; key++)
    if (bpf_map_update_elem(rules_fd, &key, &xdp_bm25_generated_rules[key],
                            BPF_ANY) != 0)
      return -1;
  for (key = 0; key < XDP_BM25_GENERATED_TERM_COUNT; key++)
    if (bpf_map_update_elem(terms_fd, &xdp_bm25_generated_terms[key].hash,
                            &xdp_bm25_generated_terms[key].value,
                            BPF_ANY) != 0)
      return -1;
  return 0;
}
#endif

static int populate_keyword_policy(struct bpf_object *obj) {
#if XDP_KEYWORD_ENABLE_NGRAM
  if (populate_jaccard_policy(obj) != 0)
    return -1;
#endif
#if XDP_KEYWORD_ENABLE_BM25
  if (populate_bm25_policy(obj) != 0)
    return -1;
#endif
  return 0;
}

#endif
