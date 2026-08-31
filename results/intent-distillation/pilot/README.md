# LoRA distillation pilot result

This is a seeded, explicitly sampled pilot, not a full MMLU-Pro test result.
The training set contains the official MMLU-Pro validation split plus the
supplement training partition. Final evaluation uses 20 seeded rows per class
from the untouched official MMLU-Pro test split plus held-out supplement rows.
All 343 evaluation prompts fit completely within XSR's 16,384-byte bound.

| Model | Teacher agreement | Accuracy | Footprint |
| --- | ---: | ---: | ---: |
| VSR mmBERT teacher | -- | 93.9% | ~616 MB base + 27 MB adapter |
| Supervised FNV student | 20.1% | 20.1% | 14 x 4096 float |
| Distilled FNV student | 19.8% | 20.1% | 14 x 4096 float |
| Quantized distilled student | 19.8% | 20.1% | 56 KiB raw weights |
| XSR eBPF student | 19.8% | 20.1% | 56 KiB raw weights |

The selected validation-only candidate used `T=2`, `alpha=0.25`, and epoch 8.
On this pilot, distillation did not improve over the identical supervised
architecture. Global int8 quantization changed zero held-out predictions.
Python integer inference and live SOCKMAP/eBPF inference matched every score,
byte count, and prediction on all 992 manifest prompts (100% agreement).

The exported file is 57,436 bytes: 57,344 int8 weights, 56 bytes of biases, and
a compact header. Its proven worst-case absolute score is 2,080,633, safely
inside signed int32.

## Performance status

No speedup is claimed. During measurement, unrelated concurrent workloads drove
host load average above 50. The warmed mmBERT path timed out at concurrency 16
and still timed out at concurrency 1, so no common valid comparison range was
available. The invalid saturation observations are retained in `summary.json`
rather than discarded, and compression/kernel/overall speedups are deliberately
left uncomputed. Re-run the existing `routing_wrk` protocol on an otherwise idle
machine before using performance numbers in a paper.
