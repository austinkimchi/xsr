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
- HTTP parser that observes content body from requests in eBPF/XDP.
- Simple n-gram domain classifier in eBPF/XDP to classify packets based on extracted signals. Identifies coding, general, or math prompts.

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

### 3. Run High-Performance Load Benchmark
Execute the high-throughput `wrk` / `wrk2` load benchmark with dataset prompts:
```bash
# Default run (Concurrency = 4, Duration = 15s)
sudo benchmarks/run_wrk_benchmark.sh

# Custom run (e.g. Concurrency = 8, Duration = 20s)
sudo CONCURRENCY=8 DURATION=20s benchmarks/run_wrk_benchmark.sh
```

Benchmark reports are saved automatically to `reports/wrk-keyword-routing/latest.md`.

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
├── reports/
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
