/*
  Header file for xdp_router.c
*/

#ifndef XDP_ROUTER_H
#define XDP_ROUTER_H

#define XDP_NGRAM_FEATURES 4096

struct xdp_ngram_weight {
  short coding;
  short general;
  short math;
};

};

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
  COUNT_ROUTE_GENERAL,
  COUNT_ROUTE_MATH,
  COUNT_MAX,
};

#endif
