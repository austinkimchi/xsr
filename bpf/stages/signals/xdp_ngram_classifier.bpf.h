#ifndef XDP_NGRAM_CLASSIFIER_BPF_H
#define XDP_NGRAM_CLASSIFIER_BPF_H

/* N-Gram is an independently selectable module; its VSR-compatible scoring
 * implementation retains the historical Jaccard names to avoid policy/map ABI churn. */
#include "xdp_jaccard_classifier.bpf.h"

#endif
