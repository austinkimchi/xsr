# XDP vs. vLLM-SR benchmark summary

- Ran on August 22, 2026 at 10:17:16 PM PDT
- Duration of test: 100s per concurrency level

| Concurrency | XDP requests/s | XDP average latency | vLLM-SR requests/s | vLLM-SR average latency | XDP throughput advantage | XDP latency advantage |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,480.75 | 385.90 us | 420.20 | 2.34 ms | 5.9x | 6.1x |
| 2 | 2,649.95 | 733.24 us | 716.21 | 2.76 ms | 3.7x | 3.8x |
| 4 | 2,736.26 | 1.42 ms | 855.20 | 4.64 ms | 3.2x | 3.3x |
| 8 | 3,086.36 | 2.54 ms | 766.01 | 10.40 ms | 4.0x | 4.1x |
| 10 | 3,178.19 | 2.44 ms | 822.16 | 9.68 ms | 3.9x | 4.0x |
| 16 | 3,045.78 | 5.20 ms | 786.13 | 20.31 ms | 3.9x | 3.9x |
| 32 | 3,319.37 | 9.59 ms | 755.24 | 42.33 ms | 4.4x | 4.4x |
| 64 | 3,323.58 | 19.19 ms | 759.93 | 84.18 ms | 4.4x | 4.4x |
| 96 | 3,063.44 | 31.25 ms | 788.23 | 121.73 ms | 3.9x | 3.9x |

## Routing-marker checks

| Metric across the sweep | XDP | vLLM-SR |
| --- | ---: | ---: |
| Aggregate route-distribution agreement | 91.26%–91.27% | 91.27%–91.35% |
| FIFO response-marker agreement | 72.92%–72.93% | 72.92%–72.97% |

## Routing-correctness checks

- 880 prompts in SPEED-Bench

| Concurrency | XDP avg ms | XDP p99 ms | XDP RPS | vLLM-SR avg ms | vLLM-SR p99 ms | vLLM-SR RPS | XSR ↔ VSR routing agreement |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.457 | 3.465 | 1,704.99 | 2.558 | 15.248 | 388.12 | 100.00% (880/880) |
| 4 | 0.862 | 5.458 | 2,946.03 | 5.408 | 29.312 | 733.42 | 100.00% (880/880) |
| 8 | 1.521 | 8.748 | 3,224.69 | 10.128 | 47.647 | 782.91 | 100.00% (880/880) |
| 16 | 2.978 | 15.817 | 3,160.88 | 19.678 | 90.214 | 802.91 | 100.00% (880/880) |

## Raw reports

- Performance: `results/routing-performance/routing_performance_{1, 2, 4, 8, 10, 16, 32, 64, 96}.md`
- Correctness: `results/routing-correctness/routing_correctness_benchmark_concurrency_{1, 4, 8, 16}.md`
