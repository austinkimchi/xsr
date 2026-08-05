/*
  Header file for xdp_router.c
*/

#ifndef XDP_ROUTER_H
#define XDP_ROUTER_H

#ifdef XDP_DEBUG
struct xdp_route_event {
  __u32 route;
  __u32 model_id;
  __u32 content_length;
  __u16 src_port;
  __u8 matched_coding;
  __u8 matched_math;
  __u64 elapsed_ns;
};
#endif

enum counter_id {
  COUNT_TOTAL,
  COUNT_IPV4,
  COUNT_TCP,
  COUNT_HTTP,
  COUNT_FRAGMENT,
  COUNT_NO_PAYLOAD,
  COUNT_CONTENT_FOUND,
  COUNT_CONTENT_PARTIAL,
  COUNT_ROUTE_CODING,
  COUNT_ROUTE_OTHERS,
  COUNT_ROUTE_MATH,
  COUNT_MAX,
};

#endif
