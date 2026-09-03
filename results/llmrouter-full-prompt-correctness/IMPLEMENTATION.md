# Implementation and truncation trace

Pinned LLMRouter revision `da3430baaea672743c3957457b0c76faba19876e`
contains the OpenClaw server used by the benchmark. In its installed
`openclaw_router/server.py`, the `/v1/chat/completions` handler:

1. finds the last user message;
2. assigns `normalize_content(raw_content)[:500]` on the ordinary text path
   (installed line 520), or `processed_text[:500]` on the media path (line 512);
3. calls `OpenClawRouter.select_model(user_query, ...)` (line 528);
4. the `llmrouter` strategy calls `LLMRouterAdapter.route(query, models)`;
5. that adapter invokes `xsr_reference.route_single({"query": query})`.

Thus the ordinary benchmark HTTP path truncated the prompt before the custom
router boundary. The pinned upstream installation was not edited.

`benchmarks/llmrouter/serve_benchmark.py` now recognizes only the
`xsr_reference` adapter configured for N-Gram or BM25. It wraps OpenClaw's
normalized routing text in a `str` subclass that preserves the complete string
for the one exact `[:500]` operation in the pinned handler. All other string
operations and the message forwarded to the selected backend retain ordinary
`str` behavior. The launcher fails closed if the expected pinned source pattern
is absent, so a future upstream change cannot be silently patched.

Intent and every non-`xsr_reference` or non-N-Gram/BM25 configuration continue
through the unmodified upstream factory. Policies, thresholds, keywords,
reference routing semantics, XSR, and the corpus are unchanged.
