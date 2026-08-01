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

## File Structure
```
.
├── models
│   ├── xdp_ngram_model_fnv.json
├── reports
│   └── xdp_benchmark_final.md
├── tests
│   └── test_ngram_routing.py
├── README.md
├── xdp_decision.bpf.h
├── xdp_http_parser.bpf.h
├── xdp_ngram_classifier.bpf.h
├── xdp_router.bpf.c
├── xdp_router.c
└── xdp_router.h
└── xdp_signals.bpf.h
```

## References
- [eBPF and XDP](https://ebpf.io/)
- [VSR: vLLM Semantic Router](https://vllm-semantic-router.com/)
