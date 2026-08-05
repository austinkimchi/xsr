#ifndef XDP_CLASSIFIER_BPF_H
#define XDP_CLASSIFIER_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>

#include <bpf/bpf_helpers.h>

#include "xdp_keyword_classifier.bpf.h"

#define MAX_SCAN 512
#define MAX_CONTENT 1500 // Default MTU size, can be adjusted as needed

#define CONTENT_KEY_LEN 10 // "content":

enum content_parse_result {
  CONTENT_NOT_FOUND = 0,
  CONTENT_COMPLETE = 1,
  CONTENT_PARTIAL = 2,
};

struct content_flow_state {
  __u32 match_pos;
  __u32 content_length;
  __u8 waiting_for_value_quote;
  __u8 in_content;
};

struct content_scan_ctx {
  struct xdp_md *xdp;
  __u32 payload_offset;
  __u32 scan_length;
  __u32 length;
  int result;
  struct content_flow_state *state;
  struct xdp_keyword_state *keyword;
};

static __always_inline unsigned char content_key_char(__u32 pos) {
  switch (pos) {
  case 0:
    return '"';
  case 1:
    return 'c';
  case 2:
    return 'o';
  case 3:
    return 'n';
  case 4:
    return 't';
  case 5:
    return 'e';
  case 6:
    return 'n';
  case 7:
    return 't';
  case 8:
    return '"';
  case 9:
    return ':';
  default:
    return 0;
  }
}

static __always_inline int content_match_key(struct content_flow_state *state,
                                             unsigned char c) {
  if (state->waiting_for_value_quote) {
    if (c == '"') {
      state->in_content = 1;
      state->waiting_for_value_quote = 0;
      state->content_length = 0;
      return CONTENT_PARTIAL;
    }

    if (c != ' ')
      state->waiting_for_value_quote = 0;

    return CONTENT_NOT_FOUND;
  }

  if (state->match_pos >= CONTENT_KEY_LEN)
    state->match_pos = 0;

  if (c == content_key_char(state->match_pos)) {
    state->match_pos++;
    if (state->match_pos == CONTENT_KEY_LEN) {
      state->match_pos = 0;
      state->waiting_for_value_quote = 1;
    }
    return CONTENT_NOT_FOUND;
  }

  state->match_pos = c == '"' ? 1 : 0;
  return CONTENT_NOT_FOUND;
}

static long scan_content_callback(__u32 i, void *data) {
  struct content_scan_ctx *ctx = (struct content_scan_ctx *)data;
  struct content_flow_state *state = ctx->state;

  unsigned char c;

  if (i >= ctx->scan_length) {
    if (state->in_content || state->waiting_for_value_quote ||
        state->match_pos != 0)
      ctx->result = CONTENT_PARTIAL;
    else
      ctx->result = CONTENT_NOT_FOUND;
    return 1;
  }

  if (bpf_xdp_load_bytes(ctx->xdp, ctx->payload_offset + i, &c, sizeof(c)) <
      0) {
    ctx->length = i;
    if (state->in_content || state->waiting_for_value_quote ||
        state->match_pos != 0)
      ctx->result = CONTENT_PARTIAL;
    else
      ctx->result = CONTENT_NOT_FOUND;
    return 1;
  }

  if (state->in_content) {
    if (c == '"') {
      ctx->length = state->content_length;
      ctx->result = CONTENT_COMPLETE;
      return 1;
    }

    state->content_length++;
    if (ctx->keyword)
      xdp_keyword_score_char(ctx->keyword, c);
    ctx->length = state->content_length;
    ctx->result = CONTENT_PARTIAL;
    return 0;
  }

  ctx->result = content_match_key(state, c);
  return 0;
}

static __always_inline int
scan_content_stream(struct xdp_md *xdp, unsigned char *data,
                    unsigned char *payload, __u32 payload_length,
                    struct content_flow_state *state,
                    struct xdp_keyword_state *keyword, __u32 *length) {
  __u32 scan_length = payload_length;

  if (scan_length > MAX_CONTENT)
    scan_length = MAX_CONTENT;

  struct content_scan_ctx ctx = {
      .xdp = xdp,
      .payload_offset = (__u32)(payload - data),
      .scan_length = scan_length,
      .length = state->content_length,
      .result = CONTENT_NOT_FOUND,
      .state = state,
      .keyword = keyword,
  };

  bpf_loop(MAX_CONTENT, scan_content_callback, &ctx, 0);

  if (ctx.result != CONTENT_COMPLETE &&
      (state->in_content || state->waiting_for_value_quote ||
       state->match_pos != 0))
    ctx.result = CONTENT_PARTIAL;

  *length = ctx.length;
  return ctx.result;
}

#endif
