#ifndef XDP_HTTP_PARSER_BPF_H
#define XDP_HTTP_PARSER_BPF_H

#include <linux/bpf.h>
#include <linux/types.h>

#include <bpf/bpf_helpers.h>

#include "xdp_classifier.bpf.h"

#define MAX_HEADER_SCAN 2000
#define MAX_PACKET_SCAN 65535

#define CONTENT_KEY_LEN 10 // "content":

enum content_parse_result {
  CONTENT_NOT_FOUND = 0,
  CONTENT_COMPLETE = 1,
  CONTENT_PARTIAL = 2,
  CONTENT_OVERSIZE = 3,
  CONTENT_NEEDS_DECODE = 4,
};

struct content_flow_state {
  __u32 match_pos;
  __u32 content_length;
  __u8 waiting_for_value_quote;
  __u8 in_content;
  __u8 escaped;
  __u8 unicode_remaining;
  __u8 needs_json_decode;
  __u16 unicode_value;
  __u16 unicode_high_surrogate;
  __u32 decode_offset;
};

struct content_scan_ctx {
  struct xdp_md *xdp;
  __u32 payload_offset;
  __u32 scan_length;
  __u32 length;
  int result;
  struct content_flow_state *state;
  struct xdp_classifier_state *classifier;
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
      state->escaped = 0;
      state->unicode_remaining = 0;
      state->needs_json_decode = 0;
      state->unicode_value = 0;
      state->unicode_high_surrogate = 0;
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

    if (c == '\\') {
      state->needs_json_decode = 1;
      state->decode_offset = i;
      ctx->result = CONTENT_NEEDS_DECODE;
      return 1;
    }

    xdp_classifier_score_char(ctx->classifier, c);
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
                    struct content_flow_state *state,
                    struct xdp_classifier_state *classifier, __u32 *length) {
  __u32 scan_length = payload_length;

  if (scan_length > MAX_PACKET_SCAN)
    return CONTENT_OVERSIZE;

  struct content_scan_ctx ctx = {
      .xdp = xdp,
      .payload_offset = (__u32)(payload - data),
      .scan_length = scan_length,
      .length = state->content_length,
      .result = CONTENT_NOT_FOUND,
      .state = state,
      .classifier = classifier,
  };

  bpf_loop(scan_length, scan_content_callback, &ctx, 0);

  if (ctx.result != CONTENT_COMPLETE &&
      ctx.result != CONTENT_NEEDS_DECODE &&
      (state->in_content || state->waiting_for_value_quote ||
       state->match_pos != 0))
    ctx.result = CONTENT_PARTIAL;

  *length = ctx.length;
  return ctx.result;
}

static __always_inline int content_hex_value(unsigned char c) {
  if (c >= '0' && c <= '9')
    return c - '0';
  if (c >= 'a' && c <= 'f')
    return c - 'a' + 10;
  if (c >= 'A' && c <= 'F')
    return c - 'A' + 10;
  return -1;
}

static __always_inline void
content_emit_decoded(struct content_scan_ctx *ctx, unsigned char c) {
  xdp_classifier_score_char(ctx->classifier, c);
  ctx->state->content_length++;
  ctx->length = ctx->state->content_length;
}

static __always_inline void
content_emit_codepoint(struct content_scan_ctx *ctx, __u32 value) {
  if (value <= 0x7f) {
    content_emit_decoded(ctx, value);
  } else if (value <= 0x7ff) {
    content_emit_decoded(ctx, 0xc0 | (value >> 6));
    content_emit_decoded(ctx, 0x80 | (value & 0x3f));
  } else if (value <= 0xffff) {
    content_emit_decoded(ctx, 0xe0 | (value >> 12));
    content_emit_decoded(ctx, 0x80 | ((value >> 6) & 0x3f));
    content_emit_decoded(ctx, 0x80 | (value & 0x3f));
  } else if (value <= 0x10ffff) {
    content_emit_decoded(ctx, 0xf0 | (value >> 18));
    content_emit_decoded(ctx, 0x80 | ((value >> 12) & 0x3f));
    content_emit_decoded(ctx, 0x80 | ((value >> 6) & 0x3f));
    content_emit_decoded(ctx, 0x80 | (value & 0x3f));
  } else {
    content_emit_decoded(ctx, ' ');
  }
}

/* This callback is used only by the tail-called escape decoder. */
static long decode_content_callback(__u32 i, void *data) {
  struct content_scan_ctx *ctx = data;
  struct content_flow_state *state = ctx->state;
  unsigned char c;
  int hex;

  if (i >= ctx->scan_length ||
      bpf_xdp_load_bytes(ctx->xdp, ctx->payload_offset + i, &c, sizeof(c)) < 0) {
    ctx->result = CONTENT_PARTIAL;
    return 1;
  }

  if (state->unicode_remaining) {
    hex = content_hex_value(c);
    if (hex < 0) {
      state->unicode_remaining = 0;
      state->unicode_value = 0;
      content_emit_decoded(ctx, ' ');
      return 0;
    }
    state->unicode_value = (state->unicode_value << 4) | hex;
    state->unicode_remaining--;
    if (!state->unicode_remaining) {
      __u32 value = state->unicode_value;
      if (value >= 0xd800 && value <= 0xdbff) {
        if (state->unicode_high_surrogate)
          content_emit_decoded(ctx, ' ');
        state->unicode_high_surrogate = value;
      } else if (value >= 0xdc00 && value <= 0xdfff &&
                 state->unicode_high_surrogate) {
        value = 0x10000 +
                (((__u32)state->unicode_high_surrogate - 0xd800) << 10) +
                (value - 0xdc00);
        state->unicode_high_surrogate = 0;
        content_emit_codepoint(ctx, value);
      } else {
        if (state->unicode_high_surrogate) {
          content_emit_decoded(ctx, ' ');
          state->unicode_high_surrogate = 0;
        }
        if (value >= 0xdc00 && value <= 0xdfff)
          content_emit_decoded(ctx, ' ');
        else
          content_emit_codepoint(ctx, value);
      }
      state->unicode_value = 0;
    }
    return 0;
  }

  if (state->escaped) {
    state->escaped = 0;
    if (c == 'u') {
      state->unicode_remaining = 4;
      state->unicode_value = 0;
    } else if (c == '"' || c == '\\' || c == '/') {
      content_emit_decoded(ctx, c);
    } else {
      /* JSON's escaped controls delimit words for this classifier. */
      content_emit_decoded(ctx, ' ');
    }
    return 0;
  }

  if (c == '"') {
    ctx->result = CONTENT_COMPLETE;
    return 1;
  }
  if (c == '\\') {
    state->escaped = 1;
    return 0;
  }

  content_emit_decoded(ctx, c);
  ctx->result = CONTENT_PARTIAL;
  return 0;
}

static __always_inline int
decode_content_stream(struct xdp_md *xdp, unsigned char *data,
                      unsigned char *payload, __u32 payload_length,
                      struct content_flow_state *state,
                      struct xdp_classifier_state *classifier, __u32 *length) {
  __u32 offset = state->decode_offset;

  if (offset > payload_length || payload_length > MAX_PACKET_SCAN)
    return CONTENT_OVERSIZE;

  struct content_scan_ctx ctx = {
      .xdp = xdp,
      .payload_offset = (__u32)(payload - data) + offset,
      .scan_length = payload_length - offset,
      .length = state->content_length,
      .result = CONTENT_PARTIAL,
      .state = state,
      .classifier = classifier,
  };

  state->decode_offset = 0;
  bpf_loop(ctx.scan_length, decode_content_callback, &ctx, 0);
  *length = ctx.length;
  return ctx.result;
}

#endif
