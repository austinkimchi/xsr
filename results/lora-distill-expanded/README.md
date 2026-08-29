# Experiment C: expanded balanced training data

Experiment C preserves the existing 343-row holdout and 72-row validation set
exactly. It expands training from 577 to 4,900 prompts (8.5x), with exactly 350
examples in each of the 14 classes. The additional rows are a deterministic
sample from MMLU-Pro rows outside the fixed holdout. They retain their official
source metadata but are explicitly marked as remapped to student training.
Consequently, this is a seeded fixed-holdout result, not full official-test
evaluation.

The frozen teacher and all student settings remain unchanged. Both students use
the 14-by-4096 linear FNV byte-trigram representation and balanced minibatch
sampling. Distillation remains `T=2`, `alpha=0.25`; no wider hash, richer n-gram,
nonlinear layer, or quantization change is introduced.

| Student | Train accuracy | Train agreement | Train macro-F1 | Test accuracy | Test agreement | Test macro-F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Supervised | 99.9% | 93.3% | 99.9% | 62.1% | 62.1% | 62.0% |
| Distilled | 93.1% | 97.0% | 93.1% | 62.4% | 63.6% | 62.4% |

## Held-out per-class recall

| Class | Supervised | Distilled |
| --- | ---: | ---: |
| biology | 75.0% | 60.7% |
| business | 60.9% | 52.2% |
| chemistry | 45.8% | 58.3% |
| computer science | 68.2% | 59.1% |
| economics | 69.6% | 56.5% |
| engineering | 79.2% | 79.2% |
| health | 52.4% | 47.6% |
| history | 72.0% | 72.0% |
| law | 57.1% | 66.7% |
| math | 57.1% | 57.1% |
| other | 55.8% | 72.1% |
| philosophy | 68.0% | 72.0% |
| physics | 69.6% | 60.9% |
| psychology | 35.0% | 45.0% |

The supervised prediction distribution is `36, 22, 12, 25, 24, 26, 21, 25,
14, 19, 38, 25, 30, 26`; the distilled distribution is `29, 19, 19, 22, 19,
27, 24, 24, 15, 20, 60, 25, 22, 18`, both in the published label order. The
true holdout contains 43 `other` rows. Thus the severe collapse is resolved:
`other` falls from 142 to 38 predictions for supervised balanced sampling and
from 165 to 60 for distilled balanced sampling.

Compared with Experiment B's matching treatment, supervised accuracy improves
by 42.3 percentage points. Distilled accuracy improves by 40.5 points, teacher
agreement by 42.0 points, and macro-F1 by 44.8 points. Substantially more
balanced data therefore resolves most of the observed generalization/collapse
failure before any capacity increase. Distillation now modestly leads the
supervised model in test accuracy and teacher agreement.

The full machine-readable report contains train/test confusion matrices,
per-class recall, prediction distributions, validation-selected epochs, exact
training counts, hashes, and loss histories in `summary.json`. Holdout identity
and every fixed prompt digest are recorded in `manifest_summary.json`.
