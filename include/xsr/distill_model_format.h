#ifndef XSR_DISTILL_MODEL_FORMAT_H
#define XSR_DISTILL_MODEL_FORMAT_H

/* Canonical deployed intent student. The on-disk header repeats these values
 * so incompatible experimental checkpoints fail closed at load time. */
#define XSR_DISTILL_MODEL_MAGIC "XSRFNV14"
#define XSR_DISTILL_MODEL_VERSION 1
#define XSR_DISTILL_CLASSES 14
#define XSR_DISTILL_BUCKETS 8192
#define XSR_DISTILL_PROMPT_BYTES 16384

#endif
