# XDP vs. vLLM-SR benchmark summary

This is the controlled `wrk` sweep run on August 17, 2026, using the shared
ngram keyword-routing policy and the 240-prompt local corpus. Each
measurement ran for 30 seconds. `wrk` was used, so these are maximum
throughput measurements: no fixed request rate was enforced.

| Concurrency | XDP requests/s | XDP average latency | vLLM-SR requests/s | vLLM-SR average latency | XDP throughput advantage | XDP latency advantage |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,483.54 | 386.52 us | 422.31 | 2.33 ms | 5.9x | 6.0x |
| 2 | 2,595.35 | 750.37 us | 722.10 | 2.73 ms | 3.6x | 3.6x |
| 4 | 2,677.35 | 1.46 ms | 911.75 | 4.35 ms | 2.9x | 3.0x |
| 8 | 3,145.49 | 2.49 ms | 934.57 | 8.52 ms | 3.4x | 3.4x |
| 10 | 3,129.70 | 2.48 ms | 937.15 | 8.49 ms | 3.3x | 3.4x |
| 16 | 3,243.16 | 4.88 ms | 931.68 | 17.13 ms | 3.5x | 3.5x |
| 32 | 3,166.40 | 10.05 ms | 932.86 | 34.26 ms | 3.4x | 3.4x |
| 64 | 3,058.34 | 20.86 ms | 932.84 | 68.53 ms | 3.3x | 3.3x |
| 96 | 3,182.66 | 30.05 ms | 931.69 | 102.87 ms | 3.4x | 3.4x |

XDP sustains roughly 3.1k requests/s from concurrency 8 onward, while the
vLLM-SR route plateaus near 930 requests/s. At concurrency 96, XDP has 3.4x
the throughput and 3.4x lower average latency (30.05 ms versus 102.87 ms).

## Routing-marker checks

The reports also include two marker-based diagnostics. They should not be
read as direct XDP-versus-vLLM-SR per-input parity: the aggregate check
compares route distributions, and the FIFO check compares response-marker
ordering.

| Metric across the sweep | XDP | vLLM-SR |
| --- | ---: | ---: |
| Aggregate route-distribution agreement | 90.86%--90.93% | 91.31%--91.54% |
| FIFO response-marker agreement | 72.51%--72.54% | 72.95%--73.02% |

For routing equivalence, use the routing-correctness benchmark, which
compares individual routing decisions. These traffic markers are operational
checks, not the parity oracle.

## Raw reports

The source reports are in
`results/routing-performance/routing_performance_c{1,2,4,8,10,16,32,64,96}_20260817_*.md`.
The most recent individual run is also available as
`results/routing-performance/latest.md`.
