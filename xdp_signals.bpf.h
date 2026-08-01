#ifndef XDP_SIGNALS_BPF_H
#define XDP_SIGNALS_BPF_H

#include <linux/types.h>

#define XDP_SIGNAL_DOMAIN_CODING (1ULL << 0)
#define XDP_SIGNAL_DOMAIN_GENERAL (1ULL << 1)
#define XDP_SIGNAL_DOMAIN_MATH (1ULL << 2)
// #define XDP_SIGNAL_KEYWORD_DEBUG (1ULL << 3) // Examples
// #define XDP_SIGNAL_LONG_PROMPT (1ULL << 5)

#endif
