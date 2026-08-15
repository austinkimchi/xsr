# XDP vs. vLLM-SR benchmark summary

This is the controlled `wrk` sweep rerun on August 14, 2026, using the
shared ngrammatic-compatible trigram keyword policy.  Each measurement ran for
30 seconds.  `wrk` was used, so these are maximum
throughput measurements: no fixed request rate was enforced.

| Concurrency | XDP requests/s | XDP average latency | vLLM-SR requests/s | vLLM-SR average latency | XDP throughput advantage | XDP latency advantage |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,516.91 | 381.14 us | 420.63 | 2.34 ms | 6.0x | 6.1x |
| 2 | 2,635.39 | 738.02 us | 720.52 | 2.74 ms | 3.7x | 3.7x |
| 4 | 2,696.18 | 1.45 ms | 911.46 | 4.35 ms | 3.0x | 3.0x |
| 8 | 3,312.24 | 2.36 ms | 946.10 | 8.41 ms | 3.5x | 3.6x |
| 10 | 3,261.86 | 2.38 ms | 939.49 | 8.47 ms | 3.5x | 3.6x |
| 16 | 3,410.32 | 4.64 ms | 941.10 | 16.96 ms | 3.6x | 3.7x |
| 32 | 3,467.61 | 9.17 ms | 941.76 | 33.94 ms | 3.7x | 3.7x |
| 64 | 3,419.94 | 18.62 ms | 937.81 | 68.13 ms | 3.6x | 3.7x |
| 96 | 3,438.79 | 27.78 ms | 938.14 | 102.15 ms | 3.7x | 3.7x |

XDP sustains roughly 3.4k requests/s from concurrency 16 onward, while the
vLLM-SR route plateaus near 940 requests/s.  At concurrency 96, XDP has 3.7x
the throughput and 3.7x lower average latency (27.78 ms versus 102.15 ms).

## Routing-marker checks

The reports also include two marker-based diagnostics.  They should not be
read as direct XSR-versus-VSR per-input parity: the aggregate check compares
route distributions, and the FIFO check compares response-marker ordering.

| Metric across the sweep | XDP | vLLM-SR |
| --- | ---: | ---: |
| Aggregate route-distribution agreement | 90.85%--90.91% | 91.27%--91.57% |
| FIFO response-marker agreement | 72.51%--72.53% | 72.94%--73.04% |

For ngrammatic semantic equivalence, use the differential tests that compare
XSR's reference matcher with the VSR/`ngrammatic` behavior; these traffic
markers are useful operational checks, not the parity oracle.

## Raw reports

The source reports are in `results/wrk-keyword-routing/wrk_benchmark_{1,2,4,8,10,16,32,64,96}.md`; the most recent individual run is also available as `results/wrk-keyword-routing/latest.md`.
