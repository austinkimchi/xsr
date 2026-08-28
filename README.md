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

Production builds do not need Python. The generated policy header is checked in
and compiled directly into the router.

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

The shared policy is [`config/policy_ngram.yaml`](config/policy_ngram.yaml). Each
route has a short keyword list. xsr compares three-character pieces so small
spelling differences can still match, then applies the policy's priority order.
Prompts without a match use the fallback backend.

To change the policy, regenerate the checked-in header from the benchmark
environment and rebuild:

```bash
make benchmark
make policy
make
```

## Benchmarks and results

Benchmark tools and Python packages are kept separate from production:

```bash
make benchmark
sudo make correctness
sudo BENCHMARK_PROFILE=quick make performance
sudo BENCHMARK_PROFILE=quick RATES="100 250 500" make performance-fixed-rate
```

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
