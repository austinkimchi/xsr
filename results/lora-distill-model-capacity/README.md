# Experiment E: student model capacity

Experiment E freezes the selected 8K hash representation, exact 4,900/72/343
train-validation-test splits, 350 examples per class, frozen teacher targets,
balanced sampling, optimizer, 12-epoch budget, and distillation configuration.
The 8K linear results are reused directly from Experiment D.

Exactly one nonlinear student is tested—there is no architecture sweep:

```text
8K hashed byte trigrams
  -> sum 16-dimensional embeddings
  -> hidden bias + ReLU
  -> 16 x 14 linear output
```

## Results

| Architecture | Student | Train accuracy | Train agreement | Train macro-F1 | Test accuracy | Test agreement | Test macro-F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 8K linear | Supervised | 99.9% | 93.3% | 99.9% | **64.1%** | **63.6%** | **63.9%** |
| Tiny MLP-16 | Supervised | 93.0% | 87.3% | 93.0% | 55.7% | 55.4% | 55.8% |
| 8K linear | Distilled | 93.2% | 96.9% | 93.2% | **64.7%** | **66.5%** | **64.9%** |
| Tiny MLP-16 | Distilled | 93.3% | 96.6% | 93.4% | 61.5% | 62.1% | 60.9% |

The MLP reduces supervised test accuracy by 8.5 percentage points. For the
primary distilled comparison, it reduces accuracy by 3.2 points, teacher
agreement by 4.4 points, and macro-F1 by 4.0 points. This is not a hidden
prediction-collapse artifact: every class is still predicted, and the MLP's
largest distilled prediction count is 49 `other` routes (14.3% of the holdout).
Distilled recall improves in only 4 classes, is unchanged in 3, and declines in
7. Supervised recall declines in 10 of 14 classes.

## Held-out per-class recall

| Class | Linear supervised | MLP supervised | Linear distilled | MLP distilled |
| --- | ---: | ---: | ---: | ---: |
| biology | 64.3% | 42.9% | 64.3% | 60.7% |
| business | 69.6% | 60.9% | 56.5% | 65.2% |
| chemistry | 41.7% | 58.3% | 58.3% | 54.2% |
| computer science | 68.2% | 59.1% | 59.1% | 68.2% |
| economics | 65.2% | 47.8% | 52.2% | 52.2% |
| engineering | 83.3% | 58.3% | 79.2% | 87.5% |
| health | 57.1% | 38.1% | 61.9% | 47.6% |
| history | 84.0% | 60.0% | 64.0% | 68.0% |
| law | 66.7% | 76.2% | 71.4% | 52.4% |
| math | 57.1% | 66.7% | 47.6% | 38.1% |
| other | 58.1% | 53.5% | 72.1% | 72.1% |
| philosophy | 68.0% | 56.0% | 76.0% | 60.0% |
| physics | 73.9% | 56.5% | 73.9% | 60.9% |
| psychology | 40.0% | 50.0% | 60.0% | 60.0% |

Prediction distributions below follow the published label order:

```text
linear supervised: 31,26,11,22,28,31,25,27,17,16,38,23,28,20
MLP supervised:    32,25,23,24,21,19,23,24,26,23,33,19,31,20

linear distilled:  29,23,17,17,17,26,24,20,19,16,60,28,27,20
MLP distilled:     28,23,18,26,18,40,28,26,12,11,49,22,22,20
```

## Size and recommendation

| Architecture | Parameters | Float32 bytes | Raw int8 weight bytes |
| --- | ---: | ---: | ---: |
| 8K linear | 114,702 | 458,808 | 114,688 |
| Tiny MLP-16 | 131,326 | 525,304 | 131,296 |

The MLP adds 14.5% parameters plus ReLU and 224 output MACs, but provides no
held-out benefit. Keep the **8K linear student** and stop the architecture
ladder. Under this deliberately narrow final-variable test, modest nonlinearity
does not close the teacher gap; the remaining limitation is most consistent
with byte-trigram features lacking mmBERT's learned semantic representation.

The supervised MLP also fits the training set less completely under the fixed
budget, so this result should not be generalized to every possible nonlinear
architecture or optimization schedule. That broader search was intentionally
out of scope. The machine-readable `summary.json` contains all train/test
metrics, per-class recall, prediction distributions, confusion matrices,
selected epochs, hashes, and loss histories.
