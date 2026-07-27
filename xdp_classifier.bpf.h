#ifndef XDP_CLASSIFIER_BPF_H
#define XDP_CLASSIFIER_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>

#include <bpf/bpf_helpers.h>

#define MAX_SCAN 512
#define MAX_CONTENT 1500

#define CONTENT_MATCH_NONE 0
#define CONTENT_MATCH_QUOTE 1
#define CONTENT_MATCH_C 2
#define CONTENT_MATCH_CO 3
#define CONTENT_MATCH_CON 4
#define CONTENT_MATCH_CONT 5
#define CONTENT_MATCH_CONTE 6
#define CONTENT_MATCH_CONTEN 7
#define CONTENT_MATCH_CONTENT 8
#define CONTENT_MATCH_KEY_QUOTE 9
#define CONTENT_MATCH_COLON 10

enum content_parse_result {
  CONTENT_NOT_FOUND = 0,
  CONTENT_COMPLETE = 1,
  CONTENT_PARTIAL = 2,
};

struct content_flow_state {
  __u32 match_state;
  __u32 content_length;
  __u8 in_content;
};

struct content_scan_ctx {
  struct xdp_md *xdp;
  __u32 payload_offset;
  __u32 scan_length;
  __u32 length;
  int result;
  struct content_flow_state *state;
};

static __always_inline void content_match_reset(struct content_flow_state *state,
                                                unsigned char c) {
  state->match_state = c == '"' ? CONTENT_MATCH_QUOTE : CONTENT_MATCH_NONE;
}

static __always_inline int content_match_key(struct content_flow_state *state,
                                             unsigned char c) {
  switch (state->match_state) {
  case CONTENT_MATCH_NONE:
    if (c == '"')
      state->match_state = CONTENT_MATCH_QUOTE;
    break;
  case CONTENT_MATCH_QUOTE:
    if (c == 'c')
      state->match_state = CONTENT_MATCH_C;
    else
      content_match_reset(state, c);
    break;
  case CONTENT_MATCH_C:
    if (c == 'o')
      state->match_state = CONTENT_MATCH_CO;
    else
      content_match_reset(state, c);
    break;
  case CONTENT_MATCH_CO:
    if (c == 'n')
      state->match_state = CONTENT_MATCH_CON;
    else
      content_match_reset(state, c);
    break;
  case CONTENT_MATCH_CON:
    if (c == 't')
      state->match_state = CONTENT_MATCH_CONT;
    else
      content_match_reset(state, c);
    break;
  case CONTENT_MATCH_CONT:
    if (c == 'e')
      state->match_state = CONTENT_MATCH_CONTE;
    else
      content_match_reset(state, c);
    break;
  case CONTENT_MATCH_CONTE:
    if (c == 'n')
      state->match_state = CONTENT_MATCH_CONTEN;
    else
      content_match_reset(state, c);
    break;
  case CONTENT_MATCH_CONTEN:
    if (c == 't')
      state->match_state = CONTENT_MATCH_CONTENT;
    else
      content_match_reset(state, c);
    break;
  case CONTENT_MATCH_CONTENT:
    if (c == '"')
      state->match_state = CONTENT_MATCH_KEY_QUOTE;
    else
      content_match_reset(state, c);
    break;
  case CONTENT_MATCH_KEY_QUOTE:
    if (c == ':')
      state->match_state = CONTENT_MATCH_COLON;
    else if (c != ' ')
      content_match_reset(state, c);
    break;
  case CONTENT_MATCH_COLON:
    if (c == '"') {
      state->in_content = 1;
      state->content_length = 0;
      return CONTENT_PARTIAL;
    }
    if (c != ' ')
      content_match_reset(state, c);
    break;
  default:
    state->match_state = CONTENT_MATCH_NONE;
    break;
  }

  return CONTENT_NOT_FOUND;
}

static long scan_content_callback(__u32 i, void *data) {
  struct content_scan_ctx *ctx = (struct content_scan_ctx *)data;
  struct content_flow_state *state = ctx->state;

  unsigned char c;

  if (i >= ctx->scan_length) {
    if (state->in_content || state->match_state != CONTENT_MATCH_NONE)
      ctx->result = CONTENT_PARTIAL;
    else
      ctx->result = CONTENT_NOT_FOUND;
    return 1;
  }

  if (bpf_xdp_load_bytes(ctx->xdp, ctx->payload_offset + i, &c, sizeof(c)) <
      0) {
    ctx->length = i;
    if (state->in_content || state->match_state != CONTENT_MATCH_NONE)
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
                    struct content_flow_state *state, __u32 *length) {
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
  };

  bpf_loop(MAX_CONTENT, scan_content_callback, &ctx, 0);

  if (ctx.result != CONTENT_COMPLETE &&
      (state->in_content || state->match_state != CONTENT_MATCH_NONE))
    ctx.result = CONTENT_PARTIAL;

  *length = ctx.length;
  return ctx.result;
}

#endif
