/*
 * SK_SKB router for application-body routing over established sockets.
 *
 * The stream parser waits until a complete HTTP request is available. The
 * verdict program classifies the JSON body and redirects the request skb to
 * the backend socket selected from sk_routes.
 */

#include <linux/bpf.h>
#include <linux/types.h>

#include <bpf/bpf_helpers.h>

#include "stages/forwarding/sockmap.bpf.h"
#include "stages/parsing/xdp_datapath_limits.h"
#include "stages/policy/decision.bpf.h"
#include "stages/signals/domains.bpf.h"
#include "stages/signals/xdp_classifier.bpf.h"
#include "xsr/router.h"

#define SK_ROUTER_MAX_SCAN 512
#define SK_ROUTER_MAX_HEADER 2000
#define SK_ROUTER_MAX_REQUEST XDP_MAX_STREAM_REQUEST_BYTES

struct sk_http_flow_state {
  __u32 header_scanned;
  __u32 header_len;
  __u32 content_length;
  __u32 request_len;
  __u32 key_pos;
  __u8 header_match;
  __u8 line_start;
  __u8 reading_length;
  __u8 invalid;
  __u8 content_key_pos;
  __u8 waiting_for_quote;
  __u8 in_content;
  __u8 escaped;
  __u8 unicode_remaining;
  __u16 unicode_value;
  __u16 unicode_high_surrogate;
  struct xdp_classifier_state classifier;
};

struct {
  __uint(type, BPF_MAP_TYPE_LRU_HASH);
  __uint(max_entries, SK_ROUTER_MAX_SOCKS);
  __type(key, __u64);
  __type(value, struct sk_http_flow_state);
} sk_http_flows SEC(".maps");

/* Per-CPU initialization storage keeps the combined signal state off the
 * verifier-limited BPF stack when N-Gram and BM25 are both enabled. */
struct {
  __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
  __uint(max_entries, 1);
  __type(key, __u32);
  __type(value, struct sk_http_flow_state);
} sk_http_flow_scratch SEC(".maps");

struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, SK_ROUTER_MAX_SOCKS);
  __type(key, __u64);
  __type(value, __u32);
} sk_route_decisions SEC(".maps");

struct {
  __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
  __uint(max_entries, COUNT_MAX);
  __type(key, __u32);
  __type(value, __u64);
} counters SEC(".maps");

static __always_inline void increment_counter(__u32 key) {
  __u64 *value = bpf_map_lookup_elem(&counters, &key);

  if (value)
    (*value)++;
}

static __always_inline unsigned char lower(unsigned char c) {
  if (c >= 'A' && c <= 'Z')
    return c + ('a' - 'A');
  return c;
}

struct sk_classify_ctx {
  struct __sk_buff *skb;
  struct sk_http_flow_state *flow;
  __u32 start;
  __u32 scan_len;
};

static __always_inline unsigned char content_length_char(__u32 pos) {
  const unsigned char name[] = "content-length:";

  return pos < sizeof(name) - 1 ? name[pos] : 0;
}

static __always_inline unsigned char content_key_char(__u32 pos) {
  switch (pos) {
  case 0:
    return '"';
  case 1:
    return 'c';
  case 2:
    return 'o';
  case 3:
    return 'n';
  case 4:
    return 't';
  case 5:
    return 'e';
  case 6:
    return 'n';
  case 7:
    return 't';
  case 8:
    return '"';
  case 9:
    return ':';
  default:
    return 0;
  }
}

static __always_inline int content_hex_value(unsigned char c) {
  if (c >= '0' && c <= '9')
    return c - '0';
  if (c >= 'a' && c <= 'f')
    return c - 'a' + 10;
  if (c >= 'A' && c <= 'F')
    return c - 'A' + 10;
  return -1;
}

static __always_inline void sk_score_codepoint(struct xdp_classifier_state *classifier,
                                               __u32 value) {
  if (value <= 0x7f) {
    xdp_classifier_score_char(classifier, value);
  } else if (value <= 0x7ff) {
    xdp_classifier_score_char(classifier, 0xc0 | (value >> 6));
    xdp_classifier_score_char(classifier, 0x80 | (value & 0x3f));
  } else if (value <= 0xffff) {
    xdp_classifier_score_char(classifier, 0xe0 | (value >> 12));
    xdp_classifier_score_char(classifier, 0x80 | ((value >> 6) & 0x3f));
    xdp_classifier_score_char(classifier, 0x80 | (value & 0x3f));
  } else if (value <= 0x10ffff) {
    xdp_classifier_score_char(classifier, 0xf0 | (value >> 18));
    xdp_classifier_score_char(classifier, 0x80 | ((value >> 12) & 0x3f));
    xdp_classifier_score_char(classifier, 0x80 | ((value >> 6) & 0x3f));
    xdp_classifier_score_char(classifier, 0x80 | (value & 0x3f));
  } else {
    xdp_classifier_score_char(classifier, ' ');
  }
}

static long scan_headers_callback(__u32 i, void *data) {
  struct sk_classify_ctx *ctx = data;
  struct sk_http_flow_state *flow = ctx->flow;
  unsigned char c = 0;
  __u32 off = ctx->start + i;

  if (i >= ctx->scan_len ||
      bpf_skb_load_bytes(ctx->skb, off, &c, sizeof(c)) < 0)
    return 1;

  flow->header_scanned = off + 1;
  if (c == (flow->header_match == 0 || flow->header_match == 2 ? '\r' : '\n'))
    flow->header_match++;
  else
    flow->header_match = c == '\r' ? 1 : 0;
  if (flow->header_match == 4) {
    flow->header_len = off + 1;
    flow->request_len = flow->header_len + flow->content_length;
    return 1;
  }
  if (flow->reading_length) {
    if (c >= '0' && c <= '9') {
      if (flow->content_length > (SK_ROUTER_MAX_REQUEST - 9) / 10)
        flow->invalid = 1;
      else
        flow->content_length = flow->content_length * 10 + c - '0';
    } else if (c == '\r') {
      flow->reading_length = 0;
    } else if (c != ' ' && c != '\t') {
      flow->invalid = 1;
    }
  } else {
    if (lower(c) == content_length_char(flow->key_pos)) {
      flow->key_pos++;
      if (flow->key_pos == 15) {
        flow->reading_length = 1;
      }
    } else {
      flow->key_pos = lower(c) == 'c' ? 1 : 0;
    }
  }
  if (c == '\n') {
    flow->line_start = 1;
    flow->key_pos = 0;
  }
  return 0;
}

static long scan_content_callback(__u32 i, void *data) {
  struct sk_classify_ctx *ctx = data;
  struct sk_http_flow_state *flow = ctx->flow;
  unsigned char c = 0;

  if (i >= ctx->scan_len ||
      bpf_skb_load_bytes(ctx->skb, ctx->start + i, &c, sizeof(c)) < 0)
    return 1;
  if (flow->in_content) {
    if (flow->unicode_remaining) {
      int hex = content_hex_value(c);

      if (hex < 0) {
        flow->unicode_remaining = 0;
        flow->unicode_value = 0;
        xdp_classifier_score_char(&flow->classifier, ' ');
        return 0;
      }
      flow->unicode_value = (flow->unicode_value << 4) | hex;
      flow->unicode_remaining--;
      if (!flow->unicode_remaining) {
        __u32 value = flow->unicode_value;
        if (value >= 0xd800 && value <= 0xdbff) {
          if (flow->unicode_high_surrogate)
            xdp_classifier_score_char(&flow->classifier, ' ');
          flow->unicode_high_surrogate = value;
        } else if (value >= 0xdc00 && value <= 0xdfff &&
                   flow->unicode_high_surrogate) {
          value = 0x10000 +
                  (((__u32)flow->unicode_high_surrogate - 0xd800) << 10) +
                  (value - 0xdc00);
          flow->unicode_high_surrogate = 0;
          sk_score_codepoint(&flow->classifier, value);
        } else {
          if (flow->unicode_high_surrogate) {
            xdp_classifier_score_char(&flow->classifier, ' ');
            flow->unicode_high_surrogate = 0;
          }
          if (value >= 0xdc00 && value <= 0xdfff)
            xdp_classifier_score_char(&flow->classifier, ' ');
          else
            sk_score_codepoint(&flow->classifier, value);
        }
        flow->unicode_value = 0;
      }
      return 0;
    }
    if (flow->escaped) {
      flow->escaped = 0;
      if (c == 'u') {
        flow->unicode_remaining = 4;
        flow->unicode_value = 0;
      } else if (c == '"' || c == '\\' || c == '/') {
        xdp_classifier_score_char(&flow->classifier, c);
      } else if (c == 'b') {
        xdp_classifier_score_char(&flow->classifier, '\b');
      } else if (c == 'f') {
        xdp_classifier_score_char(&flow->classifier, '\f');
      } else if (c == 'n') {
        xdp_classifier_score_char(&flow->classifier, '\n');
      } else if (c == 'r') {
        xdp_classifier_score_char(&flow->classifier, '\r');
      } else if (c == 't') {
        xdp_classifier_score_char(&flow->classifier, '\t');
      } else {
        xdp_classifier_score_char(&flow->classifier, ' ');
      }
      return 0;
    }
    if (c == '\\') {
      flow->escaped = 1;
      return 0;
    }
    if (c == '"')
      return 1;
    xdp_classifier_score_char(&flow->classifier, c);
    return 0;
  }
  if (flow->waiting_for_quote) {
    if (c == '"') {
      flow->in_content = 1;
      flow->waiting_for_quote = 0;
    } else if (c != ' ' && c != '\t') {
      flow->waiting_for_quote = 0;
    }
    return 0;
  }
  if (c == content_key_char(flow->content_key_pos)) {
    flow->content_key_pos++;
    if (flow->content_key_pos == 10) {
      flow->content_key_pos = 0;
      flow->waiting_for_quote = 1;
    }
  } else {
    flow->content_key_pos = c == '"' ? 1 : 0;
  }

  return 0;
}

SEC("sk_skb/stream_parser")
int sk_router_parser(struct __sk_buff *skb) {
  __u64 cookie = bpf_get_socket_cookie(skb);
  struct sk_route_entry *route_entry = bpf_map_lookup_elem(&sk_routes, &cookie);
  struct sk_http_flow_state *flow;
  struct sk_http_flow_state *initial;
  struct sk_classify_ctx ctx = {.skb = skb};
  __u32 zero = 0;
  __u32 route;

  increment_counter(COUNT_HTTP);
  if (route_entry && (route_entry->flags & SK_ROUTER_FLAG_BACKEND))
    return skb->len;
  flow = bpf_map_lookup_elem(&sk_http_flows, &cookie);
  if (!flow) {
    initial = bpf_map_lookup_elem(&sk_http_flow_scratch, &zero);
    if (!initial)
      return 0;
    __builtin_memset(initial, 0, sizeof(*initial));
    initial->line_start = 1;
    xdp_classifier_init(&initial->classifier);
    bpf_map_update_elem(&sk_http_flows, &cookie, initial, BPF_ANY);
    flow = bpf_map_lookup_elem(&sk_http_flows, &cookie);
    if (!flow)
      return 0;
  }
  ctx.flow = flow;
  if (!flow->header_len) {
    ctx.start = flow->header_scanned;
    ctx.scan_len = skb->len > ctx.start ? skb->len - ctx.start : 0;
    if (ctx.scan_len > SK_ROUTER_MAX_HEADER - ctx.start)
      ctx.scan_len = SK_ROUTER_MAX_HEADER - ctx.start;
    bpf_loop(SK_ROUTER_MAX_HEADER, scan_headers_callback, &ctx, 0);
  }
  if (!flow->header_len || flow->invalid || !flow->request_len ||
      flow->request_len > skb->len || flow->request_len > SK_ROUTER_MAX_REQUEST)
    return 0;
  ctx.start = flow->header_len;
  ctx.scan_len = flow->request_len - flow->header_len;
  bpf_loop(ctx.scan_len, scan_content_callback, &ctx, 0);
  xdp_classifier_finish(&flow->classifier);
  route = xdp_classifier_route(&flow->classifier);
  bpf_map_update_elem(&sk_route_decisions, &cookie, &route, BPF_ANY);
  return flow->request_len;
}

static __always_inline __u32 classify_request(struct __sk_buff *skb) {
  __u64 cookie = bpf_get_socket_cookie(skb);
  __u32 *route = bpf_map_lookup_elem(&sk_route_decisions, &cookie);

  return route ? *route : XDP_ROUTE_GENERAL;
}

static __always_inline __u32 model_for_route(__u32 route) {
  __u64 signals = XDP_SIGNAL_DOMAIN_OTHERS;

  if (route == SK_ROUTE_CODING)
    signals = XDP_SIGNAL_DOMAIN_CODING;
  else if (route == SK_ROUTE_MATH)
    signals = XDP_SIGNAL_DOMAIN_MATH;
  else if (route == SK_ROUTE_QA)
    signals = XDP_SIGNAL_DOMAIN_QA;
  else if (route == SK_ROUTE_WRITING)
    signals = XDP_SIGNAL_DOMAIN_WRITING;

  return xdp_decision_eval(signals);
}

SEC("sk_skb/stream_verdict")
int sk_router_verdict(struct __sk_buff *skb) {
  __u64 cookie = bpf_get_socket_cookie(skb);
  struct sk_route_entry *entry = bpf_map_lookup_elem(&sk_routes, &cookie);
  __u32 route;
  __u32 model_id;
  __u32 target_slot;
  int result;

  increment_counter(COUNT_TOTAL);

  if (!entry) {
    increment_counter(COUNT_FRAGMENT);
    return SK_DROP;
  }

  if (entry->flags & SK_ROUTER_FLAG_BACKEND) {
    increment_counter(COUNT_TCP);
    result = bpf_sk_redirect_map(skb, &sk_sock_map, entry->client_slot,
                                 SK_REDIRECT_FLAGS);
    if (result != SK_PASS)
      increment_counter(COUNT_NO_PAYLOAD);
    return result;
  }

  route = classify_request(skb);
  model_id = model_for_route(route);

  if (model_id == SK_MODEL_CODING) {
    target_slot = entry->coding_slot;
    increment_counter(COUNT_ROUTE_CODING);
  } else if (model_id == SK_MODEL_MATH) {
    target_slot = entry->math_slot;
    increment_counter(COUNT_ROUTE_MATH);
  } else if (model_id == SK_MODEL_OTHERS) {
    target_slot = entry->others_slot;
    increment_counter(COUNT_ROUTE_OTHERS);
  } else if (model_id == SK_MODEL_QA) {
    target_slot = entry->qa_slot;
    increment_counter(COUNT_ROUTE_QA);
  } else if (model_id == SK_MODEL_WRITING) {
    target_slot = entry->writing_slot;
    increment_counter(COUNT_ROUTE_WRITING);
  } else {
    return SK_DROP;
  }

  bpf_map_delete_elem(&sk_route_decisions, &cookie);
  bpf_map_delete_elem(&sk_http_flows, &cookie);
  increment_counter(COUNT_CONTENT_FOUND);
  result =
      bpf_sk_redirect_map(skb, &sk_sock_map, target_slot, SK_REDIRECT_FLAGS);
  if (result != SK_PASS)
    increment_counter(COUNT_NO_PAYLOAD);
  return result;
}

char LICENSE[] SEC("license") = "GPL";
