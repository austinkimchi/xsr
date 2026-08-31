# BM25 correctness follow-up

Run date: 2026-08-30. Baseline: `484768a` on
`fix/vsr-bm25-tokenizer`. Policy: `config/policy_bm25.yaml`. The correctness
run used the full SPEED-Bench qualitative/test plus RouterArena full corpus at
concurrency 1. This is a correctness result, not a performance benchmark.

## Supported input and agreement

- Input coverage: 9,280/9,280 prompts.
- Unsupported because of an intentional datapath bound: 0.
- XSR/VSR behavioral agreement within supported input: 9,276/9,280
  (99.9569%).
- ASCII: 8,005/8,006; non-ASCII punctuation/symbols: 815/817; Latin with
  diacritics: 304/305; non-Latin: 152/152.
- XSR agreed with the independent BM25 policy oracle on all 8,400 RouterArena
  prompts. SPEED-Bench labels are dataset categories rather than the policy
  oracle, so they are not used as BM25 ground truth.

The former 213 query-token-bound disagreements and all 17 incomplete-alias
disagreements are absent. The largest observed query had 1,458 tokens, but
that corpus value is not an implementation bound.

## General fixes and bounded state

The runtime token bound is 131,072, derived from the 256 KiB maximum inspected
stream request: one-character ASCII tokens need at least one delimiter between
successive tokens. Packet inspection remains separately bounded at 65,535
bytes. Hashing is streaming, so the former 32-byte query-token rejection was
removed.

The pinned SCOWL 2020.12.07 American-English snapshot contains 102,229
supported ASCII vocabulary entries. Porter2 filtering emits 213 non-stopword
term aliases, 197 beyond the 16 configured policy surfaces, plus 179 stop-word
entries: 392 map entries total. This remains below the 2,048-entry bound. The
previous speculative suffix generator emitted 1,294 entries, so the
vocabulary mechanism is 902 entries smaller. `derive`, `equator`,
`functionality`, `writings`, and `composer's` are covered by the vocabulary and
ordinary-possessive rules, not by prompt-specific exceptions.

The BM25 state is 144 bytes before and after the change. Against `484768a`, the
SOCKMAP parser changed from 1,254 to 1,238 BPF instructions and from 6,768 to
6,640 translated bytes; the verdict program was unchanged at 5,128 translated
bytes. Both versions live-loaded with 8,192 bytes of memlock. The production
and debug SOCKMAP builds and the legacy XDP build succeeded; the legacy object
also live-loaded and attached to `veth0`.

## Remaining VSR deviations

Four prompts remain, and no XSR exception was added:

| Case | XSR/oracle | VSR | Triggering document score |
| --- | --- | --- | ---: |
| `routerarena:full:PubMedQA_905` | qa | others | question = 1.2039728043 |
| `routerarena:full:MMLUPro_history_4643` | coding | others | function = 1.2039728043 |
| `speed-bench:qualitative:test:381` | coding | others | code = 1.2039728043 |
| `speed-bench:qualitative:test:610` | writing | others | write = 1.2039728043 |

`PubMedQA_905` returned `others` on five isolated requests against a freshly
restarted VSR and again after replaying its normal 6,259 preceding requests.
XSR and the userspace BM25 reference both return `qa`. All four cases returned
`others` three times after fresh VSR restarts while XSR and the reference
agreed. For the three Unicode cases, replacing non-ASCII code points with word
boundaries makes VSR return the same route as XSR; isolated matching snippets
also route correctly. This supports reporting deterministic VSR baseline
behavior rather than encoding benchmark-specific workarounds.

## Validation

- All 60 Python unit tests passed.
- `make check` passed on Linux 6.8.0-138-generic x86-64.
- Production SOCKMAP, debug SOCKMAP, and legacy XDP builds passed.
- Live SOCKMAP and XDP verifier loads passed.
- Full 9,280-prompt correctness corpus passed operationally at concurrency 1.

The ignored detailed local artifacts are
`results/routing-correctness/routing_correctness_bm25_concurrency_1_final.{md,json}`.
