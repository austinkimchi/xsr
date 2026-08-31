# UIUC LLMRouter baseline

This optional adapter exposes XSR's existing userspace reference computations
through UIUC LLMRouter's custom-router interface. It does not change the XSR
datapath or the VSR comparison.

The dependency is pinned to UIUC LLMRouter commit
`da3430baaea672743c3957457b0c76faba19876e` (version 0.4.0). At that revision,
a plugin supplies `route_single(query_input: dict) -> dict` and
`route_batch(batch: list) -> list`; discovery scans `./custom_routers`,
`~/.llmrouter/plugins`, and paths in `LLMROUTER_PLUGINS`.

Supported configurations:

- `configs/ngram.yaml`: XSR/VSR character N-Gram/Jaccard policy reference.
- `configs/bm25.yaml`: XSR/VSR BM25 policy reference.
- `configs/intent.yaml`: frozen INT8 FNV student; set `XSR_DISTILL_MODEL` to the
  reviewed deployment `.xsrf` artifact. The artifact remains local and ignored.

Install and run from the repository root:

```sh
make llmrouter-install
export LLMROUTER_PLUGINS="$PWD/benchmarks/llmrouter/custom_routers"
.venv-llmrouter/bin/llmrouter list-routers
.venv-llmrouter/bin/llmrouter infer --router xsr_reference \
  --config benchmarks/llmrouter/configs/ngram.yaml \
  --query "implement a function" --route-only
make test-llmrouter
```

For an OpenAI-compatible endpoint that forwards to the same five local backend
ports used by the routing harness, start those backends and run:

```sh
.venv-llmrouter/bin/llmrouter serve \
  --config benchmarks/llmrouter/configs/serve-local.yaml \
  --router xsr_reference \
  --router-config benchmarks/llmrouter/configs/ngram.yaml
```

Swap the router config for `bm25.yaml`, or for `intent.yaml` after setting
`XSR_DISTILL_MODEL`. `serve-local.yaml` contains no credentials and is only a
local baseline topology.

The adapter accepts LLMRouter's `{"query": "..."}` input and also extracts
text from `prompt` or the latest user message in an OpenAI-style `messages`
array. It returns the selected XSR route (`coding`, `math`, `qa`, `writing`, or
`others`) as LLMRouter's `model_name`/`predicted_llm` fields. LLMRouter can then
forward to candidates configured under those names.

No upstream checkout, weights, datasets, virtual environment, cache, or result
files belong in Git.
