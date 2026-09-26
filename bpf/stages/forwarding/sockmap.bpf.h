#ifndef XSR_SOCKMAP_FORWARDING_BPF_H
#define XSR_SOCKMAP_FORWARDING_BPF_H

#define SK_ROUTER_MAX_SOCKS 16384
#define SK_ROUTER_FLAG_BACKEND 1
#define SK_LIFECYCLE_REQUEST_FORWARDED 1
#define SK_LIFECYCLE_REQUEST_INCOMPLETE 2
#define SK_LIFECYCLE_REDIRECT_FAILED 4
#define SK_REDIRECT_FLAGS 0

#define SK_MODEL_CODING 1
#define SK_MODEL_MATH 2
#define SK_MODEL_OTHERS 3
#define SK_MODEL_QA 4
#define SK_MODEL_WRITING 5

#define SK_ROUTE_CODING 0
#define SK_ROUTE_GENERAL 1
#define SK_ROUTE_MATH 2
#define SK_ROUTE_QA 3
#define SK_ROUTE_WRITING 4

struct {
  __uint(type, BPF_MAP_TYPE_SOCKMAP);
  __uint(max_entries, SK_ROUTER_MAX_SOCKS);
  __type(key, __u32);
  __type(value, __u32);
} sk_sock_map SEC(".maps");

struct sk_route_entry {
  __u64 client_cookie;
  __u32 client_slot;
  __u32 coding_slot;
  __u32 math_slot;
  __u32 others_slot;
  __u32 qa_slot;
  __u32 writing_slot;
  __u32 flags;
};

struct sk_lifecycle_state {
  __u64 response_bytes_forwarded;
  __u64 request_bytes_processed;
  __u32 flags;
  __u32 reserved;
};

struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, SK_ROUTER_MAX_SOCKS);
  __type(key, __u64);
  __type(value, struct sk_route_entry);
} sk_routes SEC(".maps");

struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, SK_ROUTER_MAX_SOCKS);
  __type(key, __u64);
  __type(value, struct sk_lifecycle_state);
} sk_lifecycle SEC(".maps");

#endif
