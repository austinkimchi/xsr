/*
  Kernel XDP Program that routes packets.
  This program is loaded into the kernel by the userspace loader and attached to
  a network interface.
*/

#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/in.h>
#include <linux/ip.h>
#include <linux/tcp.h>

#include <bpf/bpf_endian.h>
#include <bpf/bpf_helpers.h>
#include <stdbool.h>

#include "xdp_decision.bpf.h"
#include "xdp_http_parser.bpf.h"
#include "xdp_router.h"
#include "xdp_signals.bpf.h"

struct {
  __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
  __uint(max_entries, COUNT_MAX);
  __type(key, __u32);
  __type(value, __u64);
} counters SEC(".maps");

#ifdef XDP_DEBUG
struct {
  __uint(type, BPF_MAP_TYPE_RINGBUF);
  __uint(max_entries, 1 << 20);
} xdp_route_events SEC(".maps");
#endif

struct http_flow_state {
  __u32 next_seq;
  __u32 body_seq;
  struct content_flow_state content;
  struct xdp_classifier_state classifier;
};

struct {
  __uint(type, BPF_MAP_TYPE_LRU_HASH);
  __uint(max_entries, 1024);
  __type(key, struct xdp_flow_key);
  __type(value, struct http_flow_state);
} http_flows SEC(".maps");

struct {
  __uint(type, BPF_MAP_TYPE_LRU_HASH);
  __uint(max_entries, 4096);
  __type(key, struct xdp_flow_key);
  __type(value, struct xdp_flow_decision);
} xdp_flow_decisions SEC(".maps");

#define XDP_TAIL_DECODE 0
struct {
  __uint(type, BPF_MAP_TYPE_PROG_ARRAY);
  __uint(max_entries, 1);
  __type(key, __u32);
  __type(value, __u32);
} xdp_tail_calls SEC(".maps");

static __always_inline void increment_counter(__u32 key) {
  __u64 *value = bpf_map_lookup_elem(&counters, &key);

  if (value)
    (*value)++;
}

static __always_inline void increment_route_counter(__u32 route) {
  if (route == XDP_ROUTE_CODING)
    increment_counter(COUNT_ROUTE_CODING);
  else if (route == XDP_ROUTE_GENERAL)
    increment_counter(COUNT_ROUTE_OTHERS);
  else if (route == XDP_ROUTE_MATH)
    increment_counter(COUNT_ROUTE_MATH);
  else if (route == XDP_ROUTE_QA)
    increment_counter(COUNT_ROUTE_QA);
  else if (route == XDP_ROUTE_WRITING)
    increment_counter(COUNT_ROUTE_WRITING);
}

#ifdef XDP_DEBUG
static __always_inline void
emit_route_event(__u32 route, __u32 model_id, __u32 content_length,
                 __u16 src_port, struct xdp_classifier_state *classifier,
                 __u64 elapsed_ns) {
  struct xdp_route_event event = {
      .route = route,
      .model_id = model_id,
      .content_length = content_length,
      .src_port = src_port,
      /* Route is already final; avoid two full rule scans solely for debug. */
      .matched_coding = route == XDP_ROUTE_CODING,
      .matched_math = route == XDP_ROUTE_MATH,
      .matched_qa = route == XDP_ROUTE_QA,
      .matched_writing = route == XDP_ROUTE_WRITING,
      .elapsed_ns = elapsed_ns,
  };

  bpf_ringbuf_output(&xdp_route_events, &event, sizeof(event), 0);
}
#endif

static __always_inline void build_flow_key(struct iphdr *ip, struct tcphdr *tcp,
                                           struct xdp_flow_key *key) {
  key->src_ip = ip->saddr;
  key->dst_ip = ip->daddr;
  key->src_port = bpf_ntohs(tcp->source);
  key->dst_port = bpf_ntohs(tcp->dest);
}

struct http_header_scan_ctx {
  struct xdp_md *xdp;
  __u32 payload_offset;
  __u32 body_offset;
};

/* Keep the header search out of the entry program's verifier state graph.
 * A regular 2,000-iteration loop compounded with the ngrammatic-compatible
 * classifier and exceeded the one-million processed-instruction limit. */
static long find_http_body_offset_callback(__u32 index, void *data) {
  struct http_header_scan_ctx *scan = data;
  unsigned char bytes[4];

  if (index >= MAX_HEADER_SCAN ||
      bpf_xdp_load_bytes(scan->xdp, scan->payload_offset + index, bytes,
                         sizeof(bytes)) < 0)
    return 1;
  if (bytes[0] != '\r' || bytes[1] != '\n' || bytes[2] != '\r' ||
      bytes[3] != '\n')
    return 0;

  scan->body_offset = index + 4;
  return 1;
}

static __always_inline int find_http_body_offset(struct xdp_md *xdp,
                                                 unsigned char *data,
                                                 unsigned char *payload,
                                                 __u32 *body_offset) {
  struct http_header_scan_ctx scan = {
      .xdp = xdp,
      .payload_offset = (__u32)(payload - data),
  };

  bpf_loop(MAX_HEADER_SCAN, find_http_body_offset_callback, &scan, 0);
  if (!scan.body_offset)
    return 0;
  *body_offset = scan.body_offset;
  return 1;
}

static __noinline void
complete_route(struct xdp_flow_key *key,
               struct xdp_classifier_state *classifier, __u32 content_length,
               __u64 elapsed_ns) {
  xdp_classifier_finish(classifier);
  __u32 route = xdp_classifier_route(classifier);
  __u64 signals = 0;

  if (route == XDP_ROUTE_CODING)
    signals |= XDP_SIGNAL_DOMAIN_CODING;
  else if (route == XDP_ROUTE_GENERAL)
    signals |= XDP_SIGNAL_DOMAIN_OTHERS;
  else if (route == XDP_ROUTE_MATH)
    signals |= XDP_SIGNAL_DOMAIN_MATH;
  else if (route == XDP_ROUTE_QA)
    signals |= XDP_SIGNAL_DOMAIN_QA;
  else if (route == XDP_ROUTE_WRITING)
    signals |= XDP_SIGNAL_DOMAIN_WRITING;

  __u32 model_id = xdp_decision_eval(signals);
  struct xdp_flow_decision decision = {
      .route = route,
      .model_id = model_id,
      .content_length = content_length,
  };

  bpf_map_update_elem(&xdp_flow_decisions, key, &decision, BPF_ANY);
#ifdef XDP_DEBUG
  emit_route_event(route, model_id, content_length, key->src_port, classifier,
                   elapsed_ns);
#endif
  increment_counter(COUNT_CONTENT_FOUND);
  increment_route_counter(route);
  bpf_map_delete_elem(&http_flows, key);
}

/* Escaped JSON strings take a separate verifier budget from the common path. */
SEC("xdp")
int xdp_decode_classify(struct xdp_md *ctx) {
#ifdef XDP_PROFILE
  __u64 start_ns = bpf_ktime_get_ns();
#endif
  void *data = (void *)(long)ctx->data;
  void *data_end = (void *)(long)ctx->data_end;
  struct ethhdr *eth = data;
  struct xdp_flow_key key = {};
  __u32 content_length = 0;

  if ((void *)(eth + 1) > data_end || eth->h_proto != bpf_htons(ETH_P_IP))
    return XDP_PASS;
  struct iphdr *ip = (void *)(eth + 1);
  if ((void *)(ip + 1) > data_end || ip->version != 4 ||
      ip->protocol != IPPROTO_TCP)
    return XDP_PASS;
  __u32 ip_header_length = ip->ihl * 4;
  if (ip_header_length < sizeof(*ip))
    return XDP_PASS;
  struct tcphdr *tcp = (void *)ip + ip_header_length;
  if ((void *)(tcp + 1) > data_end)
    return XDP_PASS;
  __u32 tcp_header_length = tcp->doff * 4;
  if (tcp_header_length < sizeof(*tcp) ||
      (void *)tcp + tcp_header_length > data_end ||
      bpf_ntohs(tcp->dest) != 18081)
    return XDP_PASS;
  unsigned char *payload = (void *)tcp + tcp_header_length;
  if (payload >= (unsigned char *)data_end)
    return XDP_PASS;
  bool close_flow = tcp->fin || tcp->rst;

  build_flow_key(ip, tcp, &key);
  struct http_flow_state *flow = bpf_map_lookup_elem(&http_flows, &key);
  if (!flow)
    return XDP_PASS;

  __u32 tcp_seq = bpf_ntohl(tcp->seq);
  __u32 payload_length = (unsigned char *)data_end - payload;
  if (tcp_seq < flow->next_seq)
    return XDP_PASS;
  if (tcp_seq > flow->next_seq) {
    flow->next_seq = tcp_seq + payload_length;
    increment_counter(COUNT_CONTENT_PARTIAL);
    return XDP_PASS;
  }

  int result = decode_content_stream(ctx, data, payload, payload_length,
                                     &flow->content, &flow->classifier,
                                     &content_length);
  if (result != CONTENT_OVERSIZE)
    flow->next_seq = tcp_seq + payload_length;

  if (result == CONTENT_COMPLETE) {
    __u64 elapsed_ns = 0;
#ifdef XDP_PROFILE
    elapsed_ns = bpf_ktime_get_ns() - start_ns;
#endif
    complete_route(&key, &flow->classifier, content_length, elapsed_ns);
  } else if (result == CONTENT_PARTIAL) {
    increment_counter(COUNT_CONTENT_PARTIAL);
  } else {
    increment_counter(COUNT_FRAGMENT);
    bpf_map_delete_elem(&http_flows, &key);
  }

  if (close_flow)
    bpf_map_delete_elem(&http_flows, &key);
  return XDP_PASS;
}

SEC("xdp")
int xdp_router(struct xdp_md *ctx) {
#ifdef XDP_PROFILE
  __u64 start_ns = bpf_ktime_get_ns();
#endif
  void *data = (void *)(long)ctx->data;
  void *data_end = (void *)(long)ctx->data_end;

  increment_counter(COUNT_TOTAL);

  // -- Ethernet Header --
  struct ethhdr *eth = data;

  // Verify Ethernet header exists before reading fields from it
  if ((void *)(eth + 1) > data_end)
    return XDP_PASS;

  // header protocol (h_proto) is stored in network byte order
  if (eth->h_proto != bpf_htons(ETH_P_IP))
    return XDP_PASS; // For now, just pass IPv4 packets

  increment_counter(COUNT_IPV4);

  // -- IP Header --
  struct iphdr *ip = (void *)(eth + 1);

  // Check if IP header is within the packet bounds
  if ((void *)(ip + 1) > data_end)
    return XDP_PASS;

  // Check ip version is 4 (IPv4)
  if (ip->version != 4)
    return XDP_PASS;

  // Ensure minimum 20-byte IPv4 header exists
  if (ip->protocol != IPPROTO_TCP)
    return XDP_PASS;

  // -- TCP Header --
  increment_counter(COUNT_TCP);

  // IHL is in 32-bit words, convert to bytes
  __u32 ip_header_length = ip->ihl * 4;

  // Verify IP header length is within the packet bounds
  if (ip_header_length < sizeof(struct iphdr))
    return XDP_PASS;

  struct tcphdr *tcp = (void *)ip + ip_header_length;

  // Check if TCP header is within the packet bounds
  if ((void *)(tcp + 1) > data_end)
    return XDP_PASS;

  // TCP header length stored in 32-bit words
  __u32 tcp_header_length = tcp->doff * 4;

  if (tcp_header_length < sizeof(struct tcphdr))
    return XDP_PASS;

  // make sure full TCP header is in the packet
  if ((void *)tcp + tcp_header_length > data_end)
    return XDP_PASS;

  // Application data starts after the TCP header
  void *payload = (void *)tcp + tcp_header_length;

  if (payload >= data_end) {
    increment_counter(COUNT_NO_PAYLOAD);
    return XDP_PASS;
  }
  bool close_flow = tcp->fin || tcp->rst;

  // -- HTTP --
  __u32 payload_length = data_end - payload;
  unsigned char *p = payload;
  struct xdp_flow_key key = {};
  struct http_flow_state *flow;
  __u32 tcp_seq = bpf_ntohl(tcp->seq);
  __u32 content_length = 0;
  int result = CONTENT_NOT_FOUND;

  // Filter only destination port 18081 (HTTP request stream)
  if (bpf_ntohs(tcp->dest) != 18081)
    return XDP_PASS;

  build_flow_key(ip, tcp, &key);

  if (p + 4 > (unsigned char *)data_end)
    return XDP_PASS;

  bool is_post = p[0] == 'P' && p[1] == 'O' && p[2] == 'S' && p[3] == 'T';

  if (is_post) {
    __u32 body_offset = 0;
    bool found_body = find_http_body_offset(ctx, data, p, &body_offset);
    struct http_flow_state new_flow = {
        .next_seq = tcp_seq,
        .body_seq = found_body ? tcp_seq + body_offset : 0,
    };

    xdp_classifier_init(&new_flow.classifier);
    bpf_map_update_elem(&http_flows, &key, &new_flow, BPF_ANY);
    flow = bpf_map_lookup_elem(&http_flows, &key);
    if (!flow)
      return XDP_PASS;

    if (found_body && body_offset < payload_length) {
      unsigned char *body = p + (__u64)body_offset;

      if (body >= (unsigned char *)data_end)
        return XDP_PASS;

      result = scan_content_stream(ctx, data, body,
                                   payload_length - body_offset, &flow->content,
                                   &flow->classifier, &content_length);
      if (result == CONTENT_NEEDS_DECODE)
        flow->content.decode_offset += body_offset;
    } else {
      result = CONTENT_PARTIAL;
    }

    if (result == CONTENT_NEEDS_DECODE) {
      bpf_tail_call(ctx, &xdp_tail_calls, XDP_TAIL_DECODE);
      flow->next_seq = tcp_seq + payload_length;
      result = CONTENT_PARTIAL;
    } else if (result == CONTENT_PARTIAL) {
      flow->next_seq = tcp_seq + payload_length;
    }
  } else {
    flow = bpf_map_lookup_elem(&http_flows, &key);
    if (!flow)
      return XDP_PASS;

    increment_counter(COUNT_HTTP);

    if (tcp_seq < flow->next_seq)
      return XDP_PASS;

    if (tcp_seq > flow->next_seq) {
      flow->next_seq = tcp_seq + payload_length;
      increment_counter(COUNT_CONTENT_PARTIAL);
      return XDP_PASS;
    }

    if (flow->content.needs_json_decode) {
      bpf_tail_call(ctx, &xdp_tail_calls, XDP_TAIL_DECODE);
      flow->next_seq = tcp_seq + payload_length;
      result = CONTENT_PARTIAL;
    } else {
      result = scan_content_stream(ctx, data, p, payload_length, &flow->content,
                                   &flow->classifier, &content_length);
      if (result == CONTENT_NEEDS_DECODE) {
        bpf_tail_call(ctx, &xdp_tail_calls, XDP_TAIL_DECODE);
        flow->next_seq = tcp_seq + payload_length;
        result = CONTENT_PARTIAL;
      }
    }
    if (result != CONTENT_OVERSIZE)
      flow->next_seq = tcp_seq + payload_length;
  }

  if (result == CONTENT_COMPLETE) {
    __u64 elapsed_ns = 0;
#ifdef XDP_PROFILE
    elapsed_ns = bpf_ktime_get_ns() - start_ns;
#endif
    complete_route(&key, &flow->classifier, content_length, elapsed_ns);
  } else if (result == CONTENT_PARTIAL) {
    increment_counter(COUNT_CONTENT_PARTIAL);
  } else if (result == CONTENT_OVERSIZE) {
    increment_counter(COUNT_FRAGMENT);
    bpf_map_delete_elem(&http_flows, &key);
  }

  if (close_flow)
    bpf_map_delete_elem(&http_flows, &key);

  return XDP_PASS;
}

char LICENSE[] SEC("license") = "GPL";
