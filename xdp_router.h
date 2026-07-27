#ifndef XDP_ROUTER_H
#define XDP_ROUTER_H
/*
  Header file for xdp_router.c
*/

enum counter_id {
  COUNT_TOTAL,
  COUNT_IPV4,
  COUNT_TCP,
  COUNT_HTTP,
  COUNT_FRAGMENT,
  COUNT_NO_PAYLOAD,
  COUNT_CONTENT_FOUND,
  COUNT_CONTENT_PARTIAL,
};

#endif