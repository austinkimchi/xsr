# xsr
xsr (XDP-based semantic routing) aims to explore the feasibility of routing LLM queries at the network layer using eBPF/XDP. The idea is to extract signals from the network layer and use them to classify packets effectively, potentially improving the routing of queries to the most suitable language model.

## Project Architecture Roadmap
```
client sends HTTPS
  -> Envoy TLS termination
  -> plaintext HTTP hop over interface
  -> eBPF processes JSON body (signals; classifier)
  -> mark (decision; AND OR operator)
  -> route (models; e.g., Qwen3-30B-A3B, GPT-5.3-Codex, Claude Opus 4.5)
```

## Current Prototype Implementation
- XDP/eBPF classifier that extracts prompt content, performs bounded
  character-n-gram set-Jaccard keyword matching, records route counters/events,
  and publishes a per-flow route decision.
- Routing proxy that performs physical backend forwarding from the XDP-produced
  decision after TLS has already been terminated to plaintext HTTP.
- Experimental SK_SKB/SOCKMAP BPF program kept for kernel-level socket-map
  routing work.
- The benchmark classifier uses exact packed ASCII n-grams rather than the
  older learned hashed/FNV classifier. The learned model remains in `models/`
  as a separate experiment and must not be described as VSR-equivalent.

## VSR-aligned keyword matching

`config/policy_ngram.yaml` is the shared XSR/VSR policy. During a build,
`scripts/generate_jaccard_policy_header.py` normalizes each ASCII keyword,
applies `ngrammatic` `Pad::Auto` boundary padding (two spaces per side for
trigrams), deduplicates packed n-grams, and emits userspace initializers.
`xdp_router` loads those initializers into fixed BPF array maps:

- `xdp_jaccard_keywords`: up to 16 keyword gram sets of up to 16 grams.
- `xdp_jaccard_rules`: up to 8 rules with route, OR/AND/NOR operator, arity,
  case mode, priority, and threshold in thousandths.
- `xdp_jaccard_config`: active keyword and rule counts.

At packet processing time, XDP collects one ASCII word at a time (letters,
digits, `_`, and `-`), deduplicates its padded grams, and uses integer
arithmetic: `intersection * 1000 >= union * threshold_milli`. The fixed
24-byte word buffer, 16 keywords, 16 grams per keyword, and trigram arity are
intentional verifier bounds. Keyword and query grams are direct packed byte
values, so there is no hash-collision approximation.

Run the reference/unit coverage with:

```bash
python3 tests/test_jaccard_keyword.py
```

The reference test covers exact matching, typos, unrelated input, case,
short words, duplicate grams, threshold inclusivity, multiple keywords, and
OR/AND/NOR semantics. Benchmark case selection uses the same reference rather
than substring matching.

### Known VSR differences

The XDP matcher reproduces VSR's ASCII case handling, word separators,
per-word matching, auto padding, and inclusive threshold interface. It does
not yet run VSR's second full-text search for multi-word phrases, and its byte
parser does not implement VSR's Unicode-aware `char::is_alphanumeric` splitter.
The pinned VSR `ngrammatic` implementation also uses a warp of 2 and occurrence
counts internally; this benchmark deliberately uses the requested unwarped,
deduplicated set-Jaccard definition. These differences should be reported with
any XSR/VSR result rather than calling decisions bit-identical.

## Routing Path
```
client
  -> TLS termination
  -> plaintext TCP connection on :18081
  -> XDP/eBPF ngram classification on veth0
  -> routing proxy reads XDP flow decision
  -> coding (:18391), math (:18392), or others (:18393)
```

The default `sk_router` control process fails startup unless all three backends
are reachable and the XDP classifier can attach to `veth0`. The experimental
SOCKMAP mode can be selected with `SK_ROUTER_MODE=sockmap`; it populates the
decision map before attaching BPF.

The checked-in vLLM-SR policy configs also map coding, math, and others to
separate marker backend ports so `wrk` can profile physical backend responses.
Restart or reload vLLM-SR after changing these configs; otherwise its response
markers can still reflect an older single-backend configuration.

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
Compile the XDP router binary, BPF object, and mock backend. The build
preprocesses the shared Jaccard policy and loads it into BPF maps:
```bash
sudo make dev
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
│   ├── xdp_classifier.bpf.h
│   ├── xdp_http_parser.bpf.h
│   ├── xdp_ngram_classifier.bpf.h
│   ├── xdp_ngram_model.generated.h
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
│   └── xdp_ngram_model_fnv.json
├── results/
│   └── wrk-keyword-routing/
├── scripts/
│   └── generate_ngram_header.py
├── Makefile
├── README.md
├── xdp_router.c
├── xdp_router.h
```

## References
- [eBPF and XDP](https://ebpf.io/)
- [VSR: vLLM Semantic Router](https://vllm-semantic-router.com/)
