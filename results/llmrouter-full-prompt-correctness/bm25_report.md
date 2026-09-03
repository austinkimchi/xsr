# LLMRouter Full-Prompt BM25 Correctness

- Concurrency: `1`
- Corpus: `9280` requests
- XSR↔LLMRouter agreement: `9280/9280` (`100.000%`)
- Reference three-way agreement: `8910/9280`
- Mismatches: `0`

## Corpus breakdown

| Source | Agreement |
| --- | ---: |
| routerarena | 8400/8400 (100.000%) |
| speed-bench | 880/880 (100.000%) |

Every row in the JSON artifact records the case identity, source index, prompt length/hash, reference route, XSR route, and end-to-end LLMRouter-selected backend.
