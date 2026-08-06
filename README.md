# xsr
xsr (XDP-based semantic routing) aims to explore the feasibility of routing LLM queries at the network layer using eBPF/XDP. The idea is to extract signals from the network layer and use them to classify packets effectively, potentially improving the routing of queries to the most suitable language model.

## Project Architecture Roadmap
```
client sends HTTPS
  -> Envoy TLS termination
  -> plaintext HTTP hop over interface
  -> eBPF processes JSON body (signals; classifier)
  -> mark (decision; AND OR operator)
  -> route (models; e.g., GPT-5.3-Codex, Claude Opus 4.5)
```

## Current Prototype Implementation
- XDP observer that extracts prompt signals and records route counters/events.
- Routing proxy that performs actual backend selection after TLS has already
  been terminated to plaintext HTTP.
- Experimental SK_SKB/SOCKMAP BPF program kept for kernel-level socket-map
  routing work.
- Simple n-gram domain classifier in eBPF to classify requests as coding,
  general, or math prompts.

## Routing Path
```
client
  -> TLS termination
  -> plaintext TCP connection on :18081
  -> routing proxy
  -> coding (:18391), math (:18392), or others (:18393)
```

The default `sk_router` control process fails startup unless all three backends
are reachable. The experimental SOCKMAP mode can be selected with
`SK_ROUTER_MODE=sockmap`; it populates the decision map before attaching BPF.

## Project MVP
- Signal extraction from the network layer
- Support some VSR Signals: keyword, complexity, domain
- Support VSR Decisions (AND OR NOT operators)
- Forward to final models

## Environment Setup & Benchmarking

### 1. Network Namespace & Interface Setup
Set up the network namespace (`ns1`) and virtual Ethernet pair (`veth0` / `veth1`):
```bash
sudo make setup
```

### 2. Build eBPF Router with Keyword Policy
Compile the XDP router binary, BPF object, and mock backend for a specific keyword policy (e.g. `policy_literal.yaml`):
```bash
sudo make KEYWORD_POLICY=config/policy_literal.yaml dev
```

### 3. Run the Routing Smoke Test
This test starts three distinct marker backends and verifies that the HTTP
response came from the selected backend, not merely from a debug event:
```bash
sudo tests/probe_sk_router_smoke.py
```

Expected backend markers are:
```json
{"backend":"coding"}
{"backend":"math"}
{"backend":"others"}
```

### 4. Run High-Performance Load Benchmark
Execute the high-throughput `wrk` / `wrk2` load benchmark with dataset prompts:
```bash
# Default run (Concurrency = 4, Duration = 15s)
sudo benchmarks/run_wrk_benchmark.sh

# Custom run (e.g. Concurrency = 8, Duration = 20s)
sudo CONCURRENCY=8 DURATION=20s benchmarks/run_wrk_benchmark.sh
```

Benchmark results are saved automatically to `results/wrk-keyword-routing/latest.md`.

## File Structure
```
.
├── bpf/
│   ├── xdp_decision.bpf.h
│   ├── xdp_http_parser.bpf.h
│   ├── xdp_keyword_classifier.bpf.h
│   ├── xdp_keyword_policy.generated.h
│   ├── xdp_router.bpf.c
│   └── xdp_signals.bpf.h
├── benchmarks/
│   ├── benchmark_keyword_routing.py
│   ├── export_dataset_prompts.py
│   ├── mock_backend.c
│   ├── prompts.lua
│   ├── run_all_keyword_benchmarks.sh
│   └── run_wrk_benchmark.sh
├── config/
│   ├── policy_bm25.yaml
│   ├── policy_exact.yaml
│   ├── policy_literal.yaml
│   ├── policy_ngram.yaml
│   └── policy_regex.yaml
├── models/
├── results/
│   └── wrk-keyword-routing/
├── scripts/
│   └── generate_keyword_header.py
├── Makefile
├── README.md
├── xdp_router.c
├── xdp_router.h
```

## References
- [eBPF and XDP](https://ebpf.io/)
- [VSR: vLLM Semantic Router](https://vllm-semantic-router.com/)
