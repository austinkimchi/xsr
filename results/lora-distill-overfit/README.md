# Experiment A: balanced-subset overfit

The unchanged 14-class, 4096-bucket FNV byte-trigram student was trained and
evaluated on the same deterministic subset: 16 examples from each class, or
224 prompts total. The run used ordinary shuffled minibatches, AdamW with the
existing learning rate and weight decay, and no class weighting or balanced
minibatch sampler.

The model passed the memorization check. Training accuracy first exceeded 99%
at epoch 6, reached 100% at epoch 10, and remained 100% through epoch 300. Every
class produced exactly 16 predictions. The confusion matrix has 16 in every
diagonal cell and zero in every off-diagonal cell, so all 14 classes were fully
memorized.

Training loss declined from 2.9086 in epoch 1 to 0.1323 at epoch 10, 0.02563 at
epoch 20, 0.003281 at epoch 100, and 0.0007314 at epoch 300. This rules out a
basic inability of the current feature generation, label mapping, gradients,
optimizer, or 4K representation to fit this small subset. The diagnostic ladder
may proceed to Experiment B; this result does not establish held-out capacity.

Reproduce the run with:

```bash
.venv-distill/bin/python benchmarks/lora_distill/overfit_balanced.py \
  --manifest benchmarks/lora_distill/artifacts/manifest_pilot.jsonl \
  --examples-per-class 16 \
  --epochs 300 \
  --output benchmarks/lora_distill/artifacts/overfit_balanced.json
```

The compact machine-readable result is in `summary.json`. The full ignored
artifact retains the complete loss and accuracy histories, exact selected row
digests, prediction distribution, and 14-by-14 confusion matrix.
