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
  __u32 route;
  __u8 debug_pos;
  __u8 function_pos;
  __u8 code_pos;
  __u8 solve_pos;
  __u8 matrix_pos;
  __u8 derivative_pos;
};

static __always_inline unsigned char kw_char(__u32 word, __u32 pos) {
  if (word == 0) {
    switch (pos) {
    case 0:
      return 'd';
    case 1:
      return 'e';
    case 2:
      return 'b';
    case 3:
      return 'u';
    case 4:
      return 'g';
    }
  } else if (word == 1) {
    switch (pos) {
    case 0:
      return 'f';
    case 1:
      return 'u';
    case 2:
      return 'n';
    case 3:
      return 'c';
    case 4:
      return 't';
    case 5:
      return 'i';
    case 6:
      return 'o';
    case 7:
      return 'n';
    }
  } else if (word == 2) {
    switch (pos) {
    case 0:
      return 'c';
    case 1:
      return 'o';
    case 2:
      return 'd';
    case 3:
      return 'e';
    }
  } else if (word == 3) {
    switch (pos) {
    case 0:
      return 's';
    case 1:
      return 'o';
    case 2:
      return 'l';
    case 3:
      return 'v';
    case 4:
      return 'e';
    }
  } else if (word == 4) {
    switch (pos) {
    case 0:
      return 'm';
    case 1:
      return 'a';
    case 2:
      return 't';
    case 3:
      return 'r';
    case 4:
      return 'i';
    case 5:
      return 'x';
    }
  } else if (word == 5) {
    switch (pos) {
    case 0:
      return 'd';
    case 1:
      return 'e';
    case 2:
      return 'r';
    case 3:
      return 'i';
    case 4:
      return 'v';
    case 5:
      return 'a';
    case 6:
      return 't';
    case 7:
      return 'i';
    case 8:
      return 'v';
    case 9:
      return 'e';
    }
  }

  return 0;
}

static __always_inline __u8 advance_kw(__u8 pos, unsigned char c, __u32 word,
                                       __u8 len) {
  if (pos < len && c == kw_char(word, pos))
    return pos + 1;
  return c == kw_char(word, 0) ? 1 : 0;
}

static long classify_callback(__u32 i, void *data) {
  struct sk_classify_ctx *ctx = data;
  unsigned char c = 0;

  if (ctx->route != SK_ROUTE_GENERAL)
    return 1;

  if (bpf_skb_load_bytes(ctx->skb, i, &c, sizeof(c)) < 0)
    return 1;

  c = lower(c);

  ctx->debug_pos = advance_kw(ctx->debug_pos, c, 0, 5);
  ctx->function_pos = advance_kw(ctx->function_pos, c, 1, 8);
  ctx->code_pos = advance_kw(ctx->code_pos, c, 2, 4);
  if (ctx->debug_pos == 5 || ctx->function_pos == 8 || ctx->code_pos == 4) {
    ctx->route = SK_ROUTE_CODING;
    return 1;
  }

  ctx->solve_pos = advance_kw(ctx->solve_pos, c, 3, 5);
  ctx->matrix_pos = advance_kw(ctx->matrix_pos, c, 4, 6);
  ctx->derivative_pos = advance_kw(ctx->derivative_pos, c, 5, 10);
  if (ctx->solve_pos == 5 || ctx->matrix_pos == 6 ||
      ctx->derivative_pos == 10) {
    ctx->route = SK_ROUTE_MATH;
    return 1;
  }

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
      .route = SK_ROUTE_GENERAL,
  };

  if (scan_len > SK_ROUTER_MAX_SCAN)
    scan_len = SK_ROUTER_MAX_SCAN;

  bpf_loop(SK_ROUTER_MAX_SCAN, classify_callback, &ctx, 0);
  return ctx.route;
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
