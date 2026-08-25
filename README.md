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
  `ngrammatic`-compatible character-n-gram matching, records route counters/events,
  and publishes a per-flow route decision.
- Routing proxy that performs physical backend forwarding from the XDP-produced
  decision after TLS has already been terminated to plaintext HTTP.
- Experimental SK_SKB/SOCKMAP BPF program kept for kernel-level socket-map
  routing work.
- The benchmark classifier uses exact packed ASCII n-grams rather than the
  older learned hashed/FNV classifier.

## VSR-aligned keyword matching

`config/policy_ngram.yaml` is the shared XSR/VSR policy. During a build,
`scripts/generate_jaccard_policy_header.py` normalizes each ASCII keyword,
applies `ngrammatic` `Pad::Auto` boundary padding (two spaces per side for
trigrams), preserves each packed n-gram's occurrence count, and emits
userspace initializers.
`xdp_router` loads those initializers into fixed BPF array maps:

- `xdp_jaccard_keywords`: up to 16 keywords, each with up to 16 total trigrams
  and per-gram occurrence counts.
- `xdp_jaccard_rules`: up to 8 rules with route, OR/AND/NOR operator, arity,
  case mode, priority, and threshold in thousandths.
- `xdp_jaccard_config`: active keyword and rule counts.

At packet processing time, XDP collects one ASCII word at a time (letters,
digits, `_`, and `-`) and preserves its gram multiplicities. It implements
`ngrammatic::Corpus::search`'s default warp of 2 with integer arithmetic:
`1 - ((all - same) / all)^2 >= threshold`, where `same` is the sum of
`min(query_count, keyword_count)` and `all = query_total + keyword_total - same`.
The comparison is inclusive. Direct packed byte grams avoid hash collisions.

The verifier bound is 16 total trigrams per keyword and query word (therefore
ASCII words up to 14 bytes for trigrams with `Pad::Auto`). Policies exceeding
that limit are rejected at build time; oversized query words are deliberately
not matched. Within that bounded ASCII subset and thresholds expressed in
thousandths, XSR has the same scoring and match decision as `ngrammatic` 0.7's
default `Corpus::search`.

Run the reference/unit coverage with:

```bash
python3 tests/test_jaccard_keyword.py
```

The reference test covers exact matching, typos, unrelated input, case,
short words, duplicate grams, threshold inclusivity, multiple keywords, and
OR/AND/NOR semantics. Benchmark case selection uses the same reference rather
than substring matching.

### Remaining VSR differences

XSR reproduces VSR's lowercased ASCII, `Pad::Auto`, trigram multiset,
warp-2, inclusive-threshold, and OR/AND/NOR behavior for the bounded subset.
The remaining differences are explicit: XSR splits only supported ASCII words
and evaluates each word independently; it does not reproduce VSR's Unicode
character handling or its second full-text search for multi-word phrases.

## Routing Path
```
client
  -> TLS termination
  -> plaintext TCP connection on :18081
  -> XDP/eBPF ngram classification on veth0
  -> routing proxy reads XDP flow decision
  -> coding (:18391), math (:18392), qa (:18394), writing (:18395), or others (:18393)
```

The default `sk_router` control process fails startup unless all five backends
are reachable and the XDP classifier can attach to `veth0`. The experimental
SOCKMAP mode can be selected with `SK_ROUTER_MODE=sockmap`; it populates the
decision map before attaching BPF.

The checked-in vLLM-SR policy config also maps coding, math, qa, writing, and others to
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

### 4. Run Routing Correctness Benchmark
Run the routing-agreement sweep across the configured concurrencies. The default modes include the direct control, SOCKMAP, and vLLM-SR; SOCKMAP is the default in-kernel forwarding path under test. Set `BENCHMARK_MODES=direct-netns,xdp,sockmap,vllm-sr` to include the legacy XDP router comparison.
```bash
make correctness
```

Results are saved under `results/routing-correctness/` as one Markdown file per
concurrency level (for example, `routing_correctness_benchmark_concurrency_4.md`).
The correctness suite fetches all 880 rows from the `nvidia/SPEED-Bench` qualitative/test split. Its `coding`, `math`, `qa`, and `writing` labels map directly to router routes; the other seven SPEED-Bench categories map to `others`.

### 5. Run High-Performance Load Benchmark
Execute the high-throughput `wrk` / `wrk2` load benchmark with dataset prompts:
```bash
# Default run: Direct Backend, XSR (SOCKMAP), and vLLM-SR
make wrk

# Custom run (e.g. Concurrency = 8, Duration = 20s)
sudo CONCURRENCY=8 DURATION=20s benchmarks/run_routing_performance.sh

# Include the legacy XDP-classified proxy for comparison
sudo make performance args="INCLUDE_XDP=1"
```

Performance results are saved under `results/routing-performance/` as
`routing_performance_<concurrency>.md`; a new run at the same concurrency
overwrites its previous report.

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
│   ├── mock_backend.c
│   ├── run_routing_correctness.sh
│   ├── run_routing_performance.sh
│   ├── routing_correctness/
│   │   ├── benchmark.py
│   │   └── run.sh
│   └── routing_wrk/
│       ├── benchmark.sh
│       ├── export_prompts.py
│       ├── prompts.lua
│       └── sweep.sh
├── config/
│   ├── policy_bm25.yaml
│   ├── policy_exact.yaml
│   ├── policy_literal.yaml
│   ├── policy_ngram.yaml
│   └── policy_regex.yaml
├── models/
│   └── xdp_ngram_model_fnv.json
├── results/
│   ├── routing-correctness/
│   └── routing-performance/
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
