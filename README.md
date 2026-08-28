# xsr

xsr is an experimental LLM request router built with eBPF and Linux SOCKMAP.
It reads a plaintext HTTP prompt after TLS termination, matches it against a
small keyword policy, and forwards the connection to a coding, math, question
answering, writing, or fallback backend.

The current work focuses on a minimal SOCKMAP router and reproducible comparisons
with a direct backend, Envoy, and vLLM Semantic Router (VSR). The older XDP path
is still available for comparison but is no longer the default.

## Installation

xsr requires Linux Kernel 6 or newer with BPF, BPF system calls, and the BPF stream
parser enabled. `make install` supports apt, dnf, and pacman systems. It installs
the C/eBPF build tools, checks SOCKMAP support, and builds the production router.

```bash
git clone https://github.com/austinkimchi/xsr.git
cd xsr/tools/XDP
make install
```

Generated policy headers are checked in for review and reproducibility. `make`
reruns the small standard-library-only Python generator so `KEYWORD_POLICY`
always controls the modules and map initializers compiled into the router.

The router expects five HTTP backends on localhost:

| Route | Port |
| --- | ---: |
| coding | 18391 |
| math | 18392 |
| fallback | 18393 |
| question answering | 18394 |
| writing | 18395 |

After those backends are running, start xsr with:

```bash
sudo ./sk_router
```

It listens for plaintext HTTP traffic on port `18081`. TLS should be terminated
before traffic reaches xsr.

## How routing works

```text
client
  -> TLS termination
  -> xsr on :18081
  -> keyword match in eBPF/SOCKMAP
  -> selected model backend
```

The checked-in examples are `config/policy_ngram.yaml`,
`config/policy_bm25.yaml`, and `config/policy_mixed.yaml`. `method: ngram` uses
the existing ngrammatic-compatible multiset Jaccard matcher; `method: bm25`
uses BM25. Rules from either module feed the same priority and backend path.
Prompts without a match use the fallback backend.

To change the policy, regenerate the checked-in header from the benchmark
environment and rebuild:

```bash
make benchmark
make KEYWORD_POLICY=config/policy_bm25.yaml policy
make KEYWORD_POLICY=config/policy_bm25.yaml
```

The policy generator writes `bpf/xdp_keyword_modules.generated.h`. Its two
feature definitions select the N-Gram and BM25 headers before clang compiles
the eBPF object, so an N-Gram-only object has no BM25 maps/code and vice versa.
Mixed policies compile both modules. This generated selection and the
userspace map initializers come from the same YAML in one generation step.

BM25 follows VSR's `bm25` 2.3 path: every rule has an independent corpus,
every keyword is one document, the request is the query, score comparison is
inclusive, and OR/AND/NOR are evaluated after per-document matching. Userspace
precomputes `k1=1.2`, `b=0.75`, average document length, BM25 IDF, and document
term weights. eBPF accumulates Q1e6 integer weights; it does not use floating
point or allocate memory.

The verifier-bounded BM25 domain is at most 8 BM25 rules, 16 total keyword
documents, 16 tokens per document, 128 corpus terms, 32 ASCII alphanumeric
bytes per query token, and 256 query tokens. Corpus FNV-1a collisions are
rejected during generation. Compatibility covers lowercased ASCII tokenization
when a match does not depend on Unicode normalization, English stop-word
removal, or stemming different surface forms (for example, `solve` versus
`solving`). Those transformations remain outside the eBPF-supported domain.
Threshold decisions within the Q1e6 rounding error of a VSR floating score are
also boundary-limited; use thresholds with at least a small margin.

## Benchmarks and results

Benchmark tools and Python packages are kept separate from production:

```bash
make benchmark
sudo make correctness
sudo BENCHMARK_PROFILE=quick make performance
sudo BENCHMARK_PROFILE=quick RATES="100 250 500" make performance-fixed-rate
```

Select BM25 in the existing workflow with:

```bash
sudo make correctness # runs N-Gram and BM25 policies
sudo make performance args="KEYWORD_POLICY=config/policy_bm25.yaml BENCHMARK_PROFILE=quick"
sudo make performance-fixed-rate args="KEYWORD_POLICY=config/policy_bm25.yaml BENCHMARK_PROFILE=quick RATES='100 250 500'"
```

For XSR/VSR agreement or comparative timing, mount that same policy into the
external VSR deployment before running the command; the benchmark does not
restart or rewrite a user-managed VSR container.
Use `KEYWORD_METHODS=bm25` (or `ngram`) to run one correctness configuration
after the matching VSR policy is active.

Use `BENCHMARK_PROFILE=paper` for the longer five-trial runs. Docker and a VSR
deployment are required for the VSR and Envoy comparisons. Add
`args="INCLUDE_XDP=1"` to a performance command only when the legacy XDP result
is needed.

The published saturation and fixed-rate data is under
[`results/routing-performance`](results/routing-performance). The analysis is in
[`results/wrk_benchmark_analysis.ipynb`](results/wrk_benchmark_analysis.ipynb).
Notebook chart exports are off by default; set `CREATE_ARTIFACTS = True` in its
first settings cell to create local PNG, PDF, and CSV copies. Those exports,
large logs, generated prompts, and other local run folders are ignored by Git.

## Legacy XDP path

SOCKMAP is the default build and runtime path. Build the older XDP router only
when an earlier experiment needs it:

```bash
make legacy
```

## References

- [Linux SOCKMAP documentation](https://docs.kernel.org/bpf/map_sockmap.html)
- [eBPF and XDP](https://ebpf.io/)
- [vLLM Semantic Router](https://vllm-semantic-router.com/)
- [VSR BM25 classifier source](https://github.com/vllm-project/semantic-router/blob/main/nlp-binding/src/bm25_classifier.rs)
- [`bm25` 2.3 crate](https://docs.rs/bm25/2.3.2/bm25/)

## File Structure

```text
.
├── bpf/                 eBPF programs, shared helpers, and checked-in policy
├── benchmarks/
│   ├── policy/          policy generators and reference tests
│   ├── routing_correctness/
│   └── routing_wrk/     load runner, analysis helpers, wrk, and wrk2 setup
├── config/              shared routing policy
├── results/             published run data and analysis notebook
├── scripts/             Linux dependency and SOCKMAP checks
├── Makefile
├── sk_router.c          primary SOCKMAP router
├── xdp_router.c         legacy XDP router
└── xdp_router.h         shared route definitions
```
