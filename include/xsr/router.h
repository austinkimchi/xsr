/*
  Shared routing data structures for XSR userspace and BPF programs.
*/

#ifndef XDP_ROUTER_H
#define XDP_ROUTER_H

#include <linux/types.h>

struct xdp_ngram_weight {
  __s32 coding;
  __s32 general;
  __s32 math;
  __s32 qa;
  __s32 writing;
};

#ifndef XDP_ROUTE_CODING
#define XDP_ROUTE_CODING 0
#define XDP_ROUTE_GENERAL 1
#define XDP_ROUTE_MATH 2
#define XDP_ROUTE_QA 3
#define XDP_ROUTE_WRITING 4
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
  COUNT_ROUTE_QA,
  COUNT_ROUTE_WRITING,
  COUNT_MAX,
};

#endif
