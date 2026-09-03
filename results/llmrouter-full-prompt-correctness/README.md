# LLMRouter full-prompt correctness ledger

This directory contains the corrected, correctness-only XSR↔LLMRouter evidence.
The original pinned-wrapper results remain unchanged in their original location:

- N-Gram: 8,776/9,280 (94.569%)
- BM25: 8,662/9,280 (93.341%)
- Intent: 1,400/1,400 (100%); not rerun or modified here

## Corrected results

| Signal | SPEED-Bench | RouterArena | Total | Mismatches |
| --- | ---: | ---: | ---: | ---: |
| N-Gram | 880/880 | 8,400/8,400 | 9,280/9,280 | 0 |
| BM25 | 880/880 | 8,400/8,400 | 9,280/9,280 | 0 |

Both runs used concurrency 1 and compared the actual backend selected by a fresh
SOCKMAP/XSR request with the `model` selected by the pinned OpenClaw/LLMRouter
HTTP path for the same case ID. No mismatch files exist because both mismatch
counts are zero.

## Artifacts

- `ngram_full_corpus.json` and `bm25_full_corpus.json`: one compact observation
  per corpus entry, including case ID, source/index, prompt length/hash, policy
  reference route, XSR route, LLMRouter route, and agreement flags.
- `ngram_report.md` and `bm25_report.md`: compact human-readable reports.
- `IMPLEMENTATION.md`: truncation trace and benchmark-only integration change.
- `REGRESSION_TESTS.md`: focused and existing-suite test evidence.
- `PROVENANCE.json`: pinned revisions, corpus identities, commands, and scope.
- `SHA256SUMS`: hashes for code, policies/configs, and correctness evidence.

No performance benchmark was run. Existing XSR, VSR, Intent, and benchmark
artifacts were not modified.
