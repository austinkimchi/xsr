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

struct tcp_flow_key {
  __u32 src_ip;
  __u32 dst_ip;
  __u16 src_port;
  __u16 dst_port;
};

struct http_flow_state {
  __u32 next_seq;
  __u32 body_seq;
  struct content_flow_state content;
  struct xdp_ngram_state ngram;
};

struct {
  __uint(type, BPF_MAP_TYPE_LRU_HASH);
  __uint(max_entries, 1024);
  __type(key, struct tcp_flow_key);
  __type(value, struct http_flow_state);
} http_flows SEC(".maps");

static __always_inline void increment_counter(__u32 key) {
  __u64 *value = bpf_map_lookup_elem(&counters, &key);

  if (value)
    (*value)++;
}

static __always_inline void increment_route_counter(__u32 route) {
  if (route == XDP_NGRAM_ROUTE_CODING)
    increment_counter(COUNT_ROUTE_CODING);
  else if (route == XDP_NGRAM_ROUTE_GENERAL)
    increment_counter(COUNT_ROUTE_GENERAL);
  else if (route == XDP_NGRAM_ROUTE_MATH)
    increment_counter(COUNT_ROUTE_MATH);
}

#ifdef XDP_DEBUG
static __always_inline void emit_route_event(__u32 route, __u32 model_id,
                                             __u32 content_length,
                                             struct xdp_ngram_state *ngram,
                                             __u64 elapsed_ns) {
  struct xdp_route_event event = {
      .route = route,
      .model_id = model_id,
      .content_length = content_length,
      .coding_score = ngram->coding,
      .general_score = ngram->general,
      .math_score = ngram->math,
      .elapsed_ns = elapsed_ns,
  };

  bpf_ringbuf_output(&xdp_route_events, &event, sizeof(event), 0);
}
#endif

static __always_inline void build_flow_key(struct iphdr *ip, struct tcphdr *tcp,
                                           struct tcp_flow_key *key) {
  key->src_ip = ip->saddr;
  key->dst_ip = ip->daddr;
  key->src_port = bpf_ntohs(tcp->source);
  key->dst_port = bpf_ntohs(tcp->dest);
}

static __always_inline int find_http_body_offset(unsigned char *payload,
                                                 unsigned char *data_end,
                                                 __u32 *body_offset) {
  for (int i = 0; i < MAX_SCAN; i++) {
    unsigned char *p = payload + i;

    if (p + 4 > data_end)
      return 0;

    if (p[0] == '\r' && p[1] == '\n' && p[2] == '\r' && p[3] == '\n') {
      *body_offset = i + 4;
      return 1;
    }
  }

  return 0;
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

  // -- HTTP --
  __u32 payload_length = data_end - payload;
  unsigned char *p = payload;
  struct tcp_flow_key key = {};
  struct http_flow_state *flow;
  __u32 tcp_seq = bpf_ntohl(tcp->seq);
  __u32 content_length = 0;
  int result = CONTENT_NOT_FOUND;

  if (p + 4 > (unsigned char *)data_end)
    return XDP_PASS;

  build_flow_key(ip, tcp, &key);

  // New HTTP requests start a bounded per-flow scan; continuation packets use
  // this state even though they do not start with an HTTP method.
  bool is_post = p[0] == 'P' && p[1] == 'O' && p[2] == 'S' && p[3] == 'T';
  if (is_post) {
    struct http_flow_state initial = {};
    __u32 body_offset = 0;
    bool found_body = find_http_body_offset(p, data_end, &body_offset);

    initial.next_seq = tcp_seq + payload_length;
    if (found_body)
      initial.body_seq = tcp_seq + body_offset;
    xdp_ngram_init(&initial.ngram);

    bpf_map_update_elem(&http_flows, &key, &initial, BPF_ANY);
    flow = bpf_map_lookup_elem(&http_flows, &key);
    if (!flow)
      return XDP_PASS;

    increment_counter(COUNT_HTTP);

    if (found_body && body_offset < payload_length) {
      result = scan_content_stream(ctx, data, p + body_offset,
                                   payload_length - body_offset, &flow->content,
                                   &flow->ngram, &content_length);
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

    result = scan_content_stream(ctx, data, p, payload_length, &flow->content,
                                 &flow->ngram, &content_length);
    flow->next_seq = tcp_seq + payload_length;
  }

  if (result == CONTENT_COMPLETE) {
    __u32 route = xdp_ngram_route_for_scores(&flow->ngram);
    __u64 signals = 0;

    if (route == XDP_NGRAM_ROUTE_CODING)
      signals |= XDP_SIGNAL_DOMAIN_CODING;
    else if (route == XDP_NGRAM_ROUTE_GENERAL)
      signals |= XDP_SIGNAL_DOMAIN_GENERAL;
    else if (route == XDP_NGRAM_ROUTE_MATH)
      signals |= XDP_SIGNAL_DOMAIN_MATH;

    __u32 model_id = xdp_decision_eval(signals);

#ifdef XDP_DEBUG
    __u64 elapsed_ns = 0;
#ifdef XDP_PROFILE
    elapsed_ns = bpf_ktime_get_ns() - start_ns;
#endif
    emit_route_event(route, model_id, content_length, &flow->ngram,
                     elapsed_ns);
#endif

    increment_counter(COUNT_CONTENT_FOUND);
    increment_route_counter(route);
    bpf_map_delete_elem(&http_flows, &key);
  } else if (result == CONTENT_PARTIAL) {
    increment_counter(COUNT_CONTENT_PARTIAL);
  }

  if (tcp->fin || tcp->rst)
    bpf_map_delete_elem(&http_flows, &key);

  return XDP_PASS;
}

char LICENSE[] SEC("license") = "GPL";
