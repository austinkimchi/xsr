# Experiment D: FNV hash-width capacity

Experiment D uses the exact Experiment C data and frozen teacher targets. The
4K metrics are reused directly; only the 8K and 16K students are newly trained.
The pipeline rejects the run unless the expanded-manifest hash, teacher-target
hash, ordered 343-row holdout digests, 72-row validation set, and 350 examples
per class all match Experiment C.

Byte normalization, trigram extraction, 32-bit FNV-1a, linear architecture,
balanced sampling, 12-epoch budget, AdamW settings, and distillation settings
(`T=2`, `alpha=0.25`) remain fixed. Width changes only the final power-of-two
hash mask and embedding-table size.

## Aggregate results

| Width | Student | Train accuracy | Train agreement | Train macro-F1 | Test accuracy | Test agreement | Test macro-F1 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4K | Supervised | 99.9% | 93.3% | 99.9% | 62.1% | 62.1% | 62.0% |
| 4K | Distilled | 93.1% | 97.0% | 93.1% | 62.4% | 63.6% | 62.4% |
| 8K | Supervised | 99.9% | 93.3% | 99.9% | 64.1% | 63.6% | 63.9% |
| 8K | Distilled | 93.2% | 96.9% | 93.2% | 64.7% | 66.5% | 64.9% |
| 16K | Supervised | 99.7% | 93.3% | 99.7% | 67.1% | 67.1% | 67.2% |
| 16K | Distilled | 93.2% | 96.7% | 93.2% | 61.5% | 63.0% | 61.6% |

Relative to 4K, 8K improves both objectives: supervised accuracy rises 2.0
points and distilled accuracy/agreement rise 2.3/2.9 points. The recall gains
are distributed rather than caused by a new dominant class: supervised recall
improves for 8 classes, is unchanged for 3, and declines for 3; distilled recall
improves for 7, is unchanged for 4, and declines for 3. Both 8K prediction
distributions remain spread across all 14 classes, with `other` unchanged at 38
supervised and 60 distilled predictions.

The 16K result is inconsistent. Supervised accuracy improves broadly to 67.1%,
with recall gains in 9 classes, but distilled accuracy falls to 61.5% and recall
declines in 6 classes. There is no new single-class collapse, so the divergence
is not explained by a prediction-distribution shift. The small 72-row selection
set and single seed may contribute, but test results were not used to override
the validation-selected checkpoint.

The ordered fixed-holdout digest is
`1899d72a537d79b841303cc2eee91bde4d40f2463d8d2979e886cdb45224686a`.
Prediction distributions below follow the published label order:

```text
4K supervised: 36,22,12,25,24,26,21,25,14,19,38,25,30,26
8K supervised: 31,26,11,22,28,31,25,27,17,16,38,23,28,20
16K supervised: 32,22,15,20,28,25,24,28,18,18,39,25,29,20

4K distilled: 29,19,19,22,19,27,24,24,15,20,60,25,22,18
8K distilled: 29,23,17,17,17,26,24,20,19,16,60,28,27,20
16K distilled: 33,17,24,19,14,31,37,22,15,13,58,28,18,14
```

## Held-out per-class recall

| Class | 4K sup. | 8K sup. | 16K sup. | 4K dist. | 8K dist. | 16K dist. |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| biology | 75.0% | 64.3% | 71.4% | 60.7% | 64.3% | 64.3% |
| business | 60.9% | 69.6% | 65.2% | 52.2% | 56.5% | 52.2% |
| chemistry | 45.8% | 41.7% | 54.2% | 58.3% | 58.3% | 62.5% |
| computer science | 68.2% | 68.2% | 63.6% | 59.1% | 59.1% | 63.6% |
| economics | 69.6% | 65.2% | 69.6% | 56.5% | 52.2% | 43.5% |
| engineering | 79.2% | 83.3% | 79.2% | 79.2% | 79.2% | 79.2% |
| health | 52.4% | 57.1% | 61.9% | 47.6% | 61.9% | 61.9% |
| history | 72.0% | 84.0% | 80.0% | 72.0% | 64.0% | 68.0% |
| law | 57.1% | 66.7% | 71.4% | 66.7% | 71.4% | 61.9% |
| math | 57.1% | 57.1% | 66.7% | 57.1% | 47.6% | 42.9% |
| other | 55.8% | 58.1% | 60.5% | 72.1% | 72.1% | 69.8% |
| philosophy | 68.0% | 68.0% | 68.0% | 72.0% | 76.0% | 72.0% |
| physics | 69.6% | 73.9% | 73.9% | 60.9% | 73.9% | 65.2% |
| psychology | 35.0% | 40.0% | 55.0% | 45.0% | 60.0% | 40.0% |

## Size and collision impact

The training corpus contains 1,213,145 trigram occurrences and 22,006 distinct
normalized byte trigrams.

| Width | Parameters | Float32 bytes | Estimated int8 XSRF bytes | Occupied buckets | Unique-trigram collision fraction | Maximum trigrams/bucket |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4K | 57,358 | 229,432 | 57,436 | 4,072 | 81.5% | 15 |
| 8K | 114,702 | 458,808 | 114,780 | 7,656 | 65.2% | 11 |
| 16K | 229,390 | 917,560 | 229,468 | 12,346 | 43.9% | 8 |

These are exact unique-trigram occupancy statistics, not a probabilistic
estimate. Int8 sizes assume the existing global symmetric scale and 14 int32
biases; wider kernel artifacts would additionally require making the current
4K model-format and map dimensions width-aware.

## Recommendation

Use **8K** as the smallest larger width producing a clear held-out improvement
for both supervised and distilled students. Do not select 16K from this run:
its supervised gain is real, but the distilled result regresses and its size is
four times the 4K model. Even at the best width, teacher agreement is only
66.5%, so collisions explain a modest portion—not most—of the remaining gap.
The next bottleneck is likely linear-student capacity or the limitations of
byte-trigram features themselves.

The machine-readable `summary.json` contains every train/test metric, prediction
distribution, per-class recall vector, test confusion matrix, selected epoch,
loss history, hash, size, and collision statistic.
