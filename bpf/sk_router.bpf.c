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

#include "xdp_decision.bpf.h"
#include "xdp_classifier.bpf.h"
#include "xdp_router.h"
#include "xdp_signals.bpf.h"

#define SK_ROUTER_MAX_SOCKS 4096
#define SK_ROUTER_MAX_SCAN 512
#define SK_ROUTER_FLAG_BACKEND 1

#define SK_MODEL_CODING 1
#define SK_MODEL_MATH 2
#define SK_MODEL_OTHERS 3

#define SK_ROUTE_CODING 0
#define SK_ROUTE_GENERAL 1
#define SK_ROUTE_MATH 2
#define SK_REDIRECT_FLAGS BPF_F_INGRESS

struct {
  __uint(type, BPF_MAP_TYPE_SOCKMAP);
  __uint(max_entries, SK_ROUTER_MAX_SOCKS);
  __type(key, __u32);
  __type(value, __u32);
} sk_sock_map SEC(".maps");

struct sk_route_entry {
  __u32 client_slot;
  __u32 coding_slot;
  __u32 math_slot;
  __u32 others_slot;
  __u32 flags;
};

struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, SK_ROUTER_MAX_SOCKS);
  __type(key, __u64);
  __type(value, struct sk_route_entry);
} sk_routes SEC(".maps");

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
  struct xdp_classifier_state classifier;
};

static long classify_callback(__u32 i, void *data) {
  struct sk_classify_ctx *ctx = data;
  unsigned char c = 0;

  if (bpf_skb_load_bytes(ctx->skb, i, &c, sizeof(c)) < 0)
    return 1;

  xdp_classifier_score_char(&ctx->classifier, c);

  return 0;
}

static __always_inline int header_name_is_content_length(void *data,
                                                         void *data_end,
                                                         __u32 off) {
  const unsigned char name[] = "content-length:";

  for (int i = 0; i < 15; i++) {
    unsigned char *p = data + off + i;

    if ((void *)(p + 1) > data_end)
      return 0;
    if (lower(*p) != name[i])
      return 0;
  }

  return 1;
}

static __always_inline int find_http_request_len(struct __sk_buff *skb,
                                                 __u32 *request_len) {
  void *data = (void *)(long)skb->data;
  void *data_end = (void *)(long)skb->data_end;
  __u32 header_len = 0;
  __u32 content_length = 0;
  __u32 scan_len = skb->len;

  if (scan_len > SK_ROUTER_MAX_SCAN)
    scan_len = SK_ROUTER_MAX_SCAN;

  for (int i = 0; i < SK_ROUTER_MAX_SCAN; i++) {
    if ((__u32)i + 4 > scan_len)
      break;

    unsigned char *p = data + i;
    if ((void *)(p + 4) > data_end)
      break;

    if (p[0] == '\r' && p[1] == '\n' && p[2] == '\r' && p[3] == '\n') {
      header_len = i + 4;
      break;
    }
  }

  if (!header_len)
    return 0;

  for (int i = 0; i < SK_ROUTER_MAX_SCAN; i++) {
    __u32 off = i;

    if (off + 16 > header_len)
      break;
    if ((off == 0 || ({
           unsigned char *prev = data + off - 1;
           (void *)(prev + 1) <= data_end && *prev == '\n';
         })) &&
        header_name_is_content_length(data, data_end, off)) {
      off += 15;
      for (int j = 0; j < 16; j++) {
        unsigned char *p = data + off + j;

        if ((void *)(p + 1) > data_end)
          break;
        if (*p == '\r' || *p == '\n')
          break;
        if (*p >= '0' && *p <= '9')
          content_length = content_length * 10 + (*p - '0');
      }
      break;
    }
  }

  *request_len = header_len + content_length;
  if (*request_len > skb->len)
    return 0;

  return 1;
}

SEC("sk_skb/stream_parser")
int sk_router_parser(struct __sk_buff *skb) {
  return skb->len;
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

static __always_inline __u32 classify_request(struct __sk_buff *skb) {
  __u32 scan_len = skb->len;
  struct sk_classify_ctx ctx = {
      .skb = skb,
  };

  if (scan_len > SK_ROUTER_MAX_SCAN)
    scan_len = SK_ROUTER_MAX_SCAN;

  xdp_classifier_init(&ctx.classifier);
  bpf_loop(SK_ROUTER_MAX_SCAN, classify_callback, &ctx, 0);
  xdp_classifier_finish(&ctx.classifier);
  return xdp_classifier_route(&ctx.classifier);
}

static __always_inline __u32 model_for_route(__u32 route) {
  __u64 signals = XDP_SIGNAL_DOMAIN_OTHERS;

  if (route == SK_ROUTE_CODING)
    signals = XDP_SIGNAL_DOMAIN_CODING;
  else if (route == SK_ROUTE_MATH)
    signals = XDP_SIGNAL_DOMAIN_MATH;

  return xdp_decision_eval(signals);
}

SEC("sk_skb/stream_verdict")
int sk_router_verdict(struct __sk_buff *skb) {
  __u64 cookie = bpf_get_socket_cookie(skb);
  struct sk_route_entry *entry = bpf_map_lookup_elem(&sk_routes, &cookie);
  __u32 route;
  __u32 model_id;
  __u32 target_slot;

  increment_counter(COUNT_TOTAL);

  if (!entry)
    return SK_DROP;

  if (entry->flags & SK_ROUTER_FLAG_BACKEND)
    return bpf_sk_redirect_map(skb, &sk_sock_map, entry->client_slot,
                               SK_REDIRECT_FLAGS);

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
  } else {
    return SK_DROP;
  }

  increment_counter(COUNT_CONTENT_FOUND);
  return bpf_sk_redirect_map(skb, &sk_sock_map, target_slot, SK_REDIRECT_FLAGS);
}

char LICENSE[] SEC("license") = "GPL";
