# Distilling mmBERT routing into XSR

This experiment does not run mmBERT or LoRA in the kernel. It freezes the
published VSR mmBERT-32K intent classifier, uses its 14-logit distribution as
an offline training signal, and exports a separate bounded linear student for
integer inference in XSR.

```text
mmBERT-32K + intent LoRA (offline teacher)
  -> soft-target distillation
  -> 14 x 4096 FNV byte-trigram student
  -> one global int8 scale
  -> BPF array maps + int32 accumulation + integer argmax
```

## Reproducibility contract

Exact model, tokenizer, adapter, dataset revisions, file hashes, and class order
are checked in as `benchmarks/lora_distill/teacher_provenance.json` and verified
again by `teacher_targets.py`. Both published mapping files must agree with the
14 labels before inference begins. The teacher loader constructs the official
base sequence classifier and then applies the official LoRA adapter; it does not
retrain either component.

MMLU-Pro has only official `validation` and `test` splits. Its validation rows
are used for student fitting and its entire test split remains final evaluation.
The supplement's official train split is deterministically divided 80/10/10;
its middle partition is the validation-only model-selection set. Every prompt
is deduplicated across all student splits by SHA-256 of the exact normalized
byte stream. The manifest records prompt, source dataset/revision/split/index,
ground truth, student split, and normalized digest. Final test rows never enter
training or hyperparameter selection.

Student normalization is intentionally small: encode UTF-8, convert only ASCII
`A-Z` bytes to `a-z`, leave every other byte unchanged, and process at most
16,384 prompt bytes. The JSON parsers reconstruct standard escaped controls and
BMP `\\uXXXX` code points as UTF-8; the benchmark sends non-BMP text as raw
UTF-8. Consecutive three-byte windows use 32-bit FNV-1a and `hash & 4095`.

The stream parser's HTTP request cap remains 256 KiB, but learned inference is
separately bounded at 16,384 decoded prompt bytes. At most 16,382 trigrams are
scored. With int8 weights, the accumulation contribution is at most
`16,382 * 127 = 2,080,514`. The exporter adds the largest absolute quantized
bias, rejects any model whose proven bound exceeds signed int32, and stores the
bound in the model header. The loader rejects incompatible dimensions/bounds.

## Running the experiment

Use a dedicated environment because the teacher stack is not a production XSR
dependency:

```bash
python3 -m venv .venv-distill
.venv-distill/bin/pip install -r benchmarks/lora_distill/requirements.txt
mkdir -p benchmarks/lora_distill/artifacts

.venv-distill/bin/python benchmarks/lora_distill/prepare_dataset.py \
  --output benchmarks/lora_distill/artifacts/manifest.jsonl

.venv-distill/bin/python benchmarks/lora_distill/teacher_targets.py \
  --manifest benchmarks/lora_distill/artifacts/manifest.jsonl \
  --output benchmarks/lora_distill/artifacts/teacher_targets.jsonl \
  --provenance benchmarks/lora_distill/artifacts/teacher_provenance.json

.venv-distill/bin/python benchmarks/lora_distill/train_students.py \
  --manifest benchmarks/lora_distill/artifacts/manifest.jsonl \
  --teacher-targets benchmarks/lora_distill/artifacts/teacher_targets.jsonl \
  --output-dir benchmarks/lora_distill/artifacts/model

.venv-distill/bin/python benchmarks/lora_distill/evaluate.py \
  --manifest benchmarks/lora_distill/artifacts/manifest.jsonl \
  --teacher-targets benchmarks/lora_distill/artifacts/teacher_targets.jsonl \
  --model-dir benchmarks/lora_distill/artifacts/model \
  --output benchmarks/lora_distill/artifacts/evaluation.json
```

The default retains the full official test split. Resource-constrained pilot
runs may add `--test-per-class N`; this performs a seeded stratified sample of
the untouched official test split and records every selected source index in
the manifest. Such a pilot must be labeled as sampled, not as a full-test run.

Training first fits the required hard-label-only baseline with the identical
14-by-4096 architecture. It then sweeps `T={1,2,4}` and `alpha={0.25,0.5}` using
hard-label cross entropy plus temperature-scaled KL divergence. Selection is
by validation teacher agreement, with validation ground-truth accuracy as the
tie-breaker. Test metrics are calculated only after selection. Float weights,
int8 export, scale, confusion matrices, macro/weighted F1, visibility fraction,
and float-to-int8 prediction changes are retained in local artifacts.

## Kernel and parity

Build normally, then load the exported model in either SOCKMAP or legacy XDP:

```bash
make
sudo env SK_ROUTER_MODE=distill \
  XSR_DISTILL_MODEL=$PWD/benchmarks/lora_distill/artifacts/model/distilled_int8.xsrf \
  ./sk_router
```

`XSR_FRONTEND_PORT` can select a separate SOCKMAP test port when another XSR
instance already owns the default `18081` (the legacy XDP path remains fixed to
its benchmark port).

The model is 57,344 int8 weights (56 KiB) plus 56 bytes of bias and small map
metadata. Each trigram performs one array lookup and 14 fixed, verifier-safe
adds. The strict-greater argmax selects the first class on ties, exactly like
NumPy. The 14-way result maps `computer science` to the existing coding route,
`math` to math, and the other 12 intents to fallback.

`kernel_parity.py` sends a fixed prompt manifest sequentially, reads the BPF
diagnostic map, and compares all 14 scores, byte counts, and predictions against
the Python integer reference. It must report 100% before performance results are
accepted:

```bash
sudo .venv-distill/bin/python benchmarks/lora_distill/kernel_parity.py \
  --model benchmarks/lora_distill/artifacts/model/distilled_int8.xsrf \
  --prompts benchmarks/lora_distill/artifacts/manifest.jsonl
```

## Performance methodology

Reuse `benchmarks/routing_wrk` and its existing prompt file, mock backends,
duration, trials, fixed-rate/saturation validation, and metadata capture. Run:

1. warmed VSR with the fixed mmBERT teacher;
2. `userspace_student.py` with the same `.xsrf` file and prompt bound;
3. XSR with that `.xsrf` loaded into BPF maps before timing.

Use the highest common valid concurrency for the main comparison and retain all
failed/saturated trials. Record requests/second and average latency for each
path. `summarize.py` renders the requested correctness table and, when given a
three-path JSON summary, separately computes compression, kernel-placement, and
overall speedups. `prepare_speed_bench.py`, `teacher_targets.py`, and
`evaluate_agreement.py` provide the optional pinned SPEED-Bench test. It reports
agreement only; those pseudo-labeled prompts are never presented as
ground-truth intent accuracy.

Use `export_benchmark_prompts.py` to place the selected manifest split at
`benchmarks/dataset_prompts.jsonl`. Start `userspace_student.py --proxy` for the
middle path; it forwards to the same mock backends as XSR after running the
exported integer model. This keeps request bodies, weights, bounds, hashing,
integer scores, and backend behavior identical across the two student paths.

Generated manifests, model arrays, raw logits, caches, environments, and scratch
results are ignored. Only source, compact provenance, and intentional result
summaries should be committed.

## Representation-capacity diagnostic ladder

Before changing the student representation, run Experiment A against a small
balanced subset of the existing training split. This retains the 14-by-4096
linear model, byte normalization, trigrams, FNV hashing, optimizer, and ordinary
shuffled minibatches. It applies neither class weights nor balanced minibatch
sampling. Training and evaluation deliberately use the exact same rows:

```bash
.venv-distill/bin/python benchmarks/lora_distill/overfit_balanced.py \
  --manifest benchmarks/lora_distill/artifacts/manifest_pilot.jsonl \
  --examples-per-class 16 \
  --output benchmarks/lora_distill/artifacts/overfit_balanced.json
```

The diagnostic must reach at least 99% training accuracy and memorize every
class before proceeding to rebalancing, more distillation data, wider hashes,
richer n-grams, or a nonlinear student. A failure stops that experiment ladder
and triggers investigation of feature generation, collisions, label mapping,
gradients, and optimizer behavior.

Experiment B holds the pilot manifest, test split, representation, optimizer,
epoch count, and selected distillation settings fixed. It independently compares
inverse-frequency class-weighted cross-entropy and uniform-class minibatch draws
against the existing baseline; the two treatments are never combined:

```bash
.venv-distill/bin/python benchmarks/lora_distill/rebalance_experiment.py \
  --manifest benchmarks/lora_distill/artifacts/manifest_pilot.jsonl \
  --teacher-targets benchmarks/lora_distill/artifacts/teacher_targets_pilot.jsonl \
  --baseline-model-dir benchmarks/lora_distill/artifacts/model_pilot \
  --output benchmarks/lora_distill/artifacts/rebalance_experiment.json \
  --summary-output results/lora-distill-rebalance/summary.json
```

Balanced sampling makes exactly the original 577 draws per epoch. It samples
classes uniformly, recycling rows within a class when necessary, without adding
prompts to the dataset. For distilled training, class weights apply only to the
hard-label cross-entropy term; balanced sampling naturally rebalances both the
hard-label and teacher-target observations.

Experiment C keeps the fixed 343-row pilot holdout and 72-row validation set
unchanged, then deterministically samples unused MMLU-Pro rows to construct 350
training examples per class. The resulting 4,900-row training set is 8.5 times
the original size. Because some official MMLU-Pro test rows are explicitly
remapped to student training, the fixed 343-row result is a seeded holdout
experiment and must not be described as evaluation on the full official test
split.

```bash
.venv-distill/bin/python benchmarks/lora_distill/prepare_expanded_training.py \
  --full-manifest benchmarks/lora_distill/artifacts/manifest.jsonl \
  --pilot-manifest benchmarks/lora_distill/artifacts/manifest_pilot.jsonl \
  --output benchmarks/lora_distill/artifacts/manifest_expanded.jsonl \
  --summary results/lora-distill-expanded/manifest_summary.json \
  --train-per-class 350

.venv-distill/bin/python benchmarks/lora_distill/teacher_targets.py \
  --manifest benchmarks/lora_distill/artifacts/manifest_expanded.jsonl \
  --output benchmarks/lora_distill/artifacts/teacher_targets_expanded.jsonl \
  --provenance benchmarks/lora_distill/artifacts/teacher_provenance_expanded.json \
  --reuse-targets benchmarks/lora_distill/artifacts/teacher_targets_pilot.jsonl \
  --reuse-provenance benchmarks/lora_distill/artifacts/teacher_provenance_pilot.json

.venv-distill/bin/python benchmarks/lora_distill/expanded_data_experiment.py \
  --manifest benchmarks/lora_distill/artifacts/manifest_expanded.jsonl \
  --teacher-targets benchmarks/lora_distill/artifacts/teacher_targets_expanded.jsonl \
  --output-dir benchmarks/lora_distill/artifacts/model_expanded \
  --report results/lora-distill-expanded/summary.json
```
