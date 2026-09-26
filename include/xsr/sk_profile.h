#ifndef XSR_SK_PROFILE_H
#define XSR_SK_PROFILE_H

#include <linux/types.h>

enum sk_profile_stage {
  SK_PROFILE_PARSE_SIGNAL,
  SK_PROFILE_DECISION,
  SK_PROFILE_REDIRECT,
  SK_PROFILE_STAGE_COUNT,
};

struct sk_profile_value {
  __u64 count;
  __u64 total_ns;
};

#endif
