# XSR

XSR is an experimental LLM request router built with eBPF and Linux SOCKMAP.
After TLS termination, it parses a plaintext HTTP request, computes bounded
routing signals, applies a decision policy, and redirects the connection to a
model backend. The older XDP path remains available for comparison.

## Quick start

XSR requires Linux with BPF, BPF syscalls, and the BPF stream parser enabled.
The installer supports apt, dnf, and pacman systems:

```bash
git clone https://github.com/austinkimchi/xsr.git
cd xsr
make install
sudo ./sk_router
```

`make install` installs production build dependencies, checks SOCKMAP support,
and builds the production router. If dependencies are already installed, run
`make` directly. Use `make help` for the complete command list.

The router accepts plaintext HTTP on port `18081` and expects five local
backends:

| Route | Port |
| --- | ---: |
| coding | 18391 |
| math | 18392 |
| fallback | 18393 |
| question answering | 18394 |
| writing | 18395 |

## Architecture

The code follows the four request-path stages used in the research paper:

```text
request R -> parsing P -> inputs Q -> signals F -> S
          -> policy Π -> route r -> forwarding B -> backend b
```

- `bpf/stages/parsing/` bounds and parses plaintext HTTP input.
- `bpf/stages/signals/` contains N-Gram, BM25, and distilled-intent signals.
- `bpf/stages/policy/` maps signals to a route.
- `bpf/stages/forwarding/` owns SOCKMAP backend redirection data.
- `bpf/programs/` composes those stages into SOCKMAP and legacy XDP programs.

Policies live in `config/`. N-Gram and BM25 modules are generated from one
policy and compiled independently; prompts with no match use the fallback
backend. Generated headers are checked in so builds are reviewable and a fresh
clone does not depend on unpublished artifacts.

```bash
make KEYWORD_POLICY=config/policy_ngram.yaml policy
make
make KEYWORD_POLICY=config/policy_bm25.yaml policy
make
```

The kernel implementations are intentionally bounded for verifier safety.
BM25 reproduces VSR's rule-local corpus scoring with precomputed fixed-point
weights; Unicode and stemming constraints are described by the policy tests
and generator. The learned signal is a separate 14-class int8 FNV student—it
does not run mmBERT or LoRA in eBPF. See
[`docs/intent_distillation.md`](docs/intent_distillation.md) for its pinned
teacher, data protocol, training workflow, and parity gate.

## Validation and benchmarks

Fast local validation does not run performance experiments:

```bash
make test
make profile-check
```

Prepare a benchmark server only when collecting results:

```bash
make benchmark
sudo make correctness
sudo make performance args="BENCHMARK_PROFILE=paper"
sudo make performance-fixed-rate args="BENCHMARK_PROFILE=paper RATES='100 250 500'"
```

Benchmark commands write local run data below `results/`; raw runs, logs,
generated prompts, models, and notebook outputs are ignored. Review and add
only deliberate summaries. The notebook can be regenerated from a reviewed
server run with `benchmarks/routing_wrk/build_analysis_notebook.py`.

## Repository layout

```text
bpf/          eBPF programs and four-stage datapath implementation
src/          userspace loaders and SOCKMAP control process
include/xsr/  shared userspace/kernel interfaces
config/       routing policy examples
benchmarks/   correctness, performance, and distillation tooling
docs/         experiment protocols and detailed design notes
results/      selected, reviewable result summaries only
scripts/      dependency installation and host capability checks
```

Build the legacy XDP path only when an older experiment requires it:

```bash
make legacy
```

## References

- [Linux SOCKMAP documentation](https://docs.kernel.org/bpf/map_sockmap.html)
- [vLLM Semantic Router](https://vllm-semantic-router.com/)
