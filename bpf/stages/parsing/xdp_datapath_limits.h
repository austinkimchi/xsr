#ifndef XDP_DATAPATH_LIMITS_H
#define XDP_DATAPATH_LIMITS_H

/* The packet path can inspect one complete 16-bit-sized TCP payload. */
#define XDP_MAX_PACKET_SCAN_BYTES 65535U

/* The SOCKMAP stream parser rejects requests larger than this. */
#define XDP_MAX_STREAM_REQUEST_BYTES (256U * 1024U)

#endif
