# XDP vs. vLLM-SR benchmark summary

This is the controlled `wrk` sweep run on August 20, 2026, using the
shared ngrammatic-compatible trigram keyword policy.  Each measurement ran for
30 seconds.  `wrk` was used, so these are maximum
throughput measurements: no fixed request rate was enforced.

| Concurrency | XDP requests/s | XDP average latency | vLLM-SR requests/s | vLLM-SR average latency | XDP throughput advantage | XDP latency advantage |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,499.03 | 383.88 us | 417.84 | 2.35 ms | 6.0x | 6.1x |
| 2 | 2,649.05 | 734.07 us | 718.64 | 2.75 ms | 3.7x | 3.7x |
| 4 | 2,701.25 | 1.44 ms | 904.72 | 4.38 ms | 3.0x | 3.0x |
| 8 | 3,139.90 | 2.49 ms | 926.98 | 8.59 ms | 3.4x | 3.5x |
| 10 | 3,142.11 | 2.47 ms | 928.35 | 8.57 ms | 3.4x | 3.5x |
| 16 | 2,942.42 | 5.38 ms | 755.65 | 21.12 ms | 3.9x | 3.9x |
| 32 | 3,358.89 | 9.47 ms | 928.77 | 34.41 ms | 3.6x | 3.6x |
| 64 | 3,114.88 | 20.45 ms | 924.70 | 69.13 ms | 3.4x | 3.4x |
| 96 | 3,168.49 | 30.19 ms | 926.44 | 103.50 ms | 3.4x | 3.4x |

XDP sustains roughly 3.1–3.4k requests/s from concurrency 8 onward, while the
vLLM-SR route plateaus near 930 requests/s (dropping to ~756 at concurrency 16).
At concurrency 96, XDP has 3.4x the throughput and 3.4x lower average latency
(30.19 ms versus 103.50 ms).

## Routing-marker checks

The reports also include two marker-based diagnostics.  They should not be
read as direct XSR-versus-VSR per-input parity: the aggregate check compares
route distributions, and the FIFO check compares response-marker ordering.

| Metric across the sweep | XDP | vLLM-SR |
| --- | ---: | ---: |
| Aggregate route-distribution agreement | 91.27%--91.65% | 91.28%--91.65% |
| FIFO response-marker agreement | 72.91%--72.95% | 72.93%--73.09% |

For ngrammatic semantic equivalence, use the differential tests that compare
XSR's reference matcher with the VSR/`ngrammatic` behavior; these traffic
markers are useful operational checks, not the parity oracle.

## Routing-correctness checks

These results use the controlled correctness benchmark (fixed 2,728-prompt
dataset, all prompts processed exactly once) at selected concurrency levels.
Both XDP and vLLM-SR achieve 100% reference-label agreement at every level.

| Concurrency | XDP avg ms | XDP p99 ms | XDP RPS | vLLM-SR avg ms | vLLM-SR p99 ms | vLLM-SR RPS |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.407 | 0.918 | 2,081.20 | 2.543 | 4.626 | 385.60 | 
| 4 | 1.385 | 3.607 | 2,493.96 | 3.842 | 7.939 | 1,031.37 |
| 8 | 2.440 | 9.159 | 2,695.87 | 6.965 | 13.855 | 1,140.25 |
| 16 | 4.252 | 16.154 | 2,974.51 | 14.007 | 26.743 | 1,133.73 |

XSR ↔ VSR routing agreement is 100% at all tested concurrency levels (2728/2728).

## Raw reports

The routing-performance source reports are in
`results/routing-performance/routing_performance_c{1,2,4,8,10,16,32,64,96}_20260820_*.md`;
the most recent individual run is also available as
`results/routing-performance/latest.md`.

The routing-correctness source reports are in
`results/routing-correctness/concurrency_{1,4,8,16}/routing_correctness_benchmark.md`.
