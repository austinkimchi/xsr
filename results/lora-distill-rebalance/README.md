# Experiment B: isolated rebalancing treatments

This experiment retains the original 577-row training set, 72-row validation
set, untouched 343-row test set, 4096-bucket FNV byte-trigram representation,
linear architecture, optimizer, epoch budget, and distilled configuration
(`T=2`, `alpha=0.25`). Class weighting and balanced sampling are tested
separately and are not combined.

Each metric cell below is accuracy / teacher agreement / macro-F1. Train and
test confusion matrices, per-class recall, and complete prediction distributions
are retained in `summary.json` using the published 14-class label order.

| Student | Treatment | Train | Test | Test `other` predictions |
| --- | --- | ---: | ---: | ---: |
| Supervised | Existing baseline | 100.0 / 84.6 / 100.0% | 20.1 / 20.1 / 13.9% | 184/343 (53.6%) |
| Supervised | Class-weighted CE | 100.0 / 84.6 / 100.0% | 21.3 / 21.6 / 15.8% | 57/343 (16.6%) |
| Supervised | Balanced sampling | 99.7 / 84.2 / 99.7% | 19.8 / 19.5 / 12.9% | 142/343 (41.4%) |
| Distilled | Existing baseline | 86.3 / 95.7 / 81.6% | 20.1 / 19.8 / 13.9% | 207/343 (60.3%) |
| Distilled | Class-weighted CE | 87.9 / 95.3 / 84.2% | 21.6 / 21.3 / 16.7% | 188/343 (54.8%) |
| Distilled | Balanced sampling | 86.8 / 95.3 / 82.1% | 21.9 / 21.6 / 17.6% | 165/343 (48.1%) |

Rebalancing alone does not materially fix held-out performance. The largest
accuracy gain is 1.75 percentage points and the largest teacher-agreement gain
is 1.75 points. Balanced sampling reduces but does not eliminate the distilled
student's `other` collapse. Class weighting makes the supervised `other` count
look healthy, but shifts the collapse to `history`: 178/343 predictions (51.9%)
despite only 25 true history prompts. Thus the failure is not simply repaired
by correcting the training class prior.

This is a single-seed diagnostic on the existing sampled pilot, so sub-point
differences should not be treated as stable improvements. None is large enough
to change the conclusion.

The result supports proceeding to Experiment C with substantially more
distillation data while retaining the 4K representation.
