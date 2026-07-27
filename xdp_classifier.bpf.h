#ifndef XDP_CLASSIFIER_BPF_H
#define XDP_CLASSIFIER_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>

#include <bpf/bpf_helpers.h>

#define MAX_SCAN 512
#define MAX_CONTENT 1500

enum content_parse_result {
  CONTENT_NOT_FOUND = 0,
  CONTENT_COMPLETE = 1,
  CONTENT_PARTIAL = 2,
};

struct content_scan_ctx {
  struct xdp_md *xdp;
  __u32 payload_offset;
  __u32 length;
  int result;
};

static long scan_content_callback(__u32 i, void *data) {
  struct content_scan_ctx *ctx = (struct content_scan_ctx *)data;

  unsigned char c;

  if (bpf_xdp_load_bytes(ctx->xdp, ctx->payload_offset + i, &c, sizeof(c)) <
      0) {
    ctx->length = i;
    ctx->result = CONTENT_NOT_FOUND;
    return 1;
  }

  if (c == '"') {
    ctx->length = i;
    ctx->result = CONTENT_COMPLETE;
    return 1;
  }

  return 0;
}
static __always_inline int find_content_start(unsigned char *payload,
                                              unsigned char *data_end,
                                              __u32 *start) {
  for (int i = 0; i < MAX_SCAN; i++) {
    unsigned char *p = payload + i;

    if (p + 11 > data_end)
      return 0;

    if (p[0] == '"' && p[1] == 'c' && p[2] == 'o' && p[3] == 'n' &&
        p[4] == 't' && p[5] == 'e' && p[6] == 'n' && p[7] == 't' &&
        p[8] == '"' && p[9] == ':' && p[10] == '"') {
      *start = i + 11;
      return 1;
    }
  }

  return 0;
}

static __always_inline int find_content_length(struct xdp_md *xdp,
                                               unsigned char *data,
                                               unsigned char *payload,
                                               __u32 start, __u32 *length) {
  struct content_scan_ctx ctx = {
      .xdp = xdp,
      .payload_offset = (__u32)((payload + start) - data),
      .length = MAX_CONTENT,
      .result = CONTENT_PARTIAL,
  };

  bpf_loop(MAX_CONTENT, scan_content_callback, &ctx, 0);

  *length = ctx.length;
  return ctx.result;
}

static __always_inline int
extract_content(struct xdp_md *xdp, unsigned char *data, unsigned char *payload,
                unsigned char *data_end, __u32 *start, __u32 *length) {
  if (!find_content_start(payload, data_end, start))
    return CONTENT_NOT_FOUND;

  return find_content_length(xdp, data, payload, *start, length);
}

#endif