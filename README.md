# XSR

XSR is eXpress Semantic Router, an eBPF/SOCKMAP semantic router that executes
supported semantic-routing functions in the kernel datapath. After TLS
termination, XSR parses plaintext HTTP/1.1 requests and supports character
n-gram, BM25, and distilled-intent routing.

## Build

XSR requires Linux with BPF syscalls, SK_SKB stream parsing, SOCKMAP, and BPF
loop support. The paper used Ubuntu 24.04 with Linux 6.17. The installer supports
apt, dnf, and pacman systems:

```bash
make install
```

If dependencies are already installed, `make` builds the SOCKMAP router.
`make help` lists the remaining targets. The router listens on plaintext HTTP
port `18081` and connects to five local marker/model backends:

| Route | Port |
| --- | ---: |
| coding | 18391 |
| math | 18392 |
| others | 18393 |
| question answering | 18394 |
| writing | 18395 |

The request path is organized under `bpf/stages/` as parsing, signal extraction,
policy evaluation, and SOCKMAP forwarding. Routing policies are generated from
the YAML files in `config/`.

```bash
make KEYWORD_POLICY=config/policy_ngram.yaml policy
make

make KEYWORD_POLICY=config/policy_bm25.yaml policy
make
```

## Validation

Run the basic tests and build checks with:

```bash
make test
make profile-check
```

The intent path additionally requires NumPy:

```bash
make benchmark-install
make test-distill
make test-latency
```

## Benchmarks

Install the benchmark environment, create the isolated client namespace, and
run the preflight:

```bash
make benchmark-install
sudo make setup iproutes
sudo make benchmark
```

Docker is required for the VSR/Envoy paths. The benchmark expects a running VSR
deployment and verifies its active signal configuration before measuring it.
The optional LLMRouter baseline is installed at its pinned revision by
`benchmark-install` when `BENCHMARK_SYSTEMS` includes `llmrouter`.

Run routing correctness and the five-trial, 40-second standard-`wrk` throughput
sweep with:

```bash
sudo make correctness

sudo make performance \
  args="BENCHMARK_PROFILE=paper SIGNAL_PROFILE=ngram KEYWORD_POLICY=$PWD/config/policy_ngram.yaml"

sudo make performance \
  args="BENCHMARK_PROFILE=paper SIGNAL_PROFILE=bm25 KEYWORD_POLICY=$PWD/config/policy_bm25.yaml"
```

The 100 request/s latency benchmark uses the included Python open-loop client
with four persistent HTTP/1.1 connections:

```bash
sudo make performance-fixed-rate \
  args="BENCHMARK_PROFILE=paper SIGNAL_PROFILE=ngram KEYWORD_POLICY=$PWD/config/policy_ngram.yaml CONCURRENCY=4 RATES=100"

sudo make performance-fixed-rate \
  args="BENCHMARK_PROFILE=paper SIGNAL_PROFILE=bm25 KEYWORD_POLICY=$PWD/config/policy_bm25.yaml CONCURRENCY=4 RATES=100"
```

For intent runs, export the selected 8,192-feature INT8 student to `.xsrf`, set
`XSR_DISTILL_MODEL`, and use `SIGNAL_PROFILE=intent`. The distillation and export
code is in `benchmarks/lora_distill/`. Start with the scripts' `--help` output
and the included requirements:

```bash
python3 -m venv .venv-distill
.venv-distill/bin/pip install -r benchmarks/lora_distill/requirements.txt

.venv-distill/bin/python benchmarks/lora_distill/prepare_dataset.py --help
.venv-distill/bin/python benchmarks/lora_distill/teacher_targets.py --help
.venv-distill/bin/python benchmarks/lora_distill/train_students.py --help
.venv-distill/bin/python benchmarks/lora_distill/freeze_deployment.py --help
```

Pass `PROMPTS_FILE=/absolute/path/workload.jsonl` and a stable `WORKLOAD_ID` to
benchmark a prepared corpus. Without `PROMPTS_FILE`, the keyword benchmark uses
its default SPEED-Bench workload. Final results are written to `results/`.

## Ablation and profiling source

The isolated routing-function, policy, and forwarding controls are:

```bash
make ablation-routing args="--trials 5 --duration 20 --warmup 2"
make ablation-policy args="--trials 5 --duration 20 --warmup 2"
sudo make ablation-forwarding args="--trials 5 --duration 20 --warmup 2 --concurrency 64"
```

Build XSR component counters with `make profile-on-build`, then read or reset
them through `scripts/sk_profile_components.py`. The pinned VSR instrumentation
patch and its snapshot reader are in `profiling/vsr/patches/` and
`scripts/vsr_profile_components.py`.

## Layout

```text
bpf/          kernel request-path stages and composed programs
src/          userspace router and model loader
include/xsr/  shared interfaces
config/       evaluated routing policies
benchmarks/   workload, correctness, latency, ablation, and distillation source
profiling/    pinned external instrumentation patch
scripts/      installation, capability checks, and profiling readers
results/      measurements
```
