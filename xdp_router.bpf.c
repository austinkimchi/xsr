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

#include "xdp_classifier.bpf.h"
#include "xdp_router.h"

struct {
  __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
  __uint(max_entries, 8);
  __type(key, __u32);
  __type(value, __u64);
} counters SEC(".maps");

static __always_inline void increment_counter(__u32 key) {
  __u64 *value = bpf_map_lookup_elem(&counters, &key);

  if (value)
    (*value)++;
}

SEC("xdp")
int xdp_router(struct xdp_md *ctx) {
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

  if (p + 4 > (unsigned char *)data_end)
    return XDP_PASS;

  // Check for HTTP GET or POST methods
  bool is_http = (p[0] == 'G' && p[1] == 'E' && p[2] == 'T' && p[3] == ' ') ||
                 (p[0] == 'P' && p[1] == 'O' && p[2] == 'S' && p[3] == 'T');

  if (!is_http)
    return XDP_PASS;

  increment_counter(COUNT_HTTP);

  __u32 content_start = 0;
  __u32 content_length = 0;

  int result = extract_content(ctx, data, payload, data_end, &content_start,
                               &content_length);

  if (result == CONTENT_COMPLETE)
    increment_counter(COUNT_CONTENT_FOUND);
  else if (result == CONTENT_PARTIAL)
    increment_counter(COUNT_CONTENT_PARTIAL);

  return XDP_PASS;
}

char LICENSE[] SEC("license") = "GPL";