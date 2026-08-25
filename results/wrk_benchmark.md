# XDP vs. vLLM-SR benchmark summary

- Ran on August 25, 2026 at 02:11:40 PM PDT
- Duration of test: 100s per concurrency level
- Routing path: XSR (SOCKMAP)

| Concurrency | XSR requests/s | XSR average latency | vLLM-SR requests/s | vLLM-SR average latency | XSR throughput advantage | XSR latency advantage |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,523.56 | 378.69 us | 330.61 | 2.99 ms | 7.6x | 7.9x |
| 2 | 4,519.80 | 424.78 us | 504.75 | 3.93 ms | 9.0x | 9.3x |
| 4 | 8,301.85 | 464.29 us | 510.81 | 7.78 ms | 16.3x | 16.8x |
| 8 | 7,522.25 | 1.02 ms | 592.79 | 13.45 ms | 12.7x | 13.2x |
| 10 | 8,339.12 | 0.92 ms | 557.86 | 14.29 ms | 14.9x | 15.5x |
| 16 | 9,153.49 | 1.44 ms | 537.86 | 29.70 ms | 17.0x | 20.6x |
| 32 | 8,708.15 | 2.36 ms | 554.46 | 57.68 ms | 15.7x | 24.4x |
| 64 | 8,065.99 | 4.48 ms | 600.47 | 106.54 ms | 13.4x | 23.8x |
| 96 | 8,901.90 | 5.85 ms | 577.53 | 166.05 ms | 15.4x | 28.4x |
| 128 | 9,751.76 | 6.98 ms | 634.93 | 201.30 ms | 15.4x | 28.8x |
| 144 | 9,495.03 | 8.01 ms | 568.54 | 252.88 ms | 16.7x | 31.6x |
| 160 | 9,045.46 | 9.29 ms | 557.31 | 286.57 ms | 16.2x | 30.8x |
| 176 | 7,851.81 | 10.80 ms | 605.29 | 290.27 ms | 13.0x | 26.9x |
| 192 | 8,282.77 | 10.25 ms | 595.43 | 321.79 ms | 13.9x | 31.4x |
| 256 | 8,278.51 | 10.12 ms | 536.66 | 475.61 ms | 15.4x | 47.0x |
| 512 | 5,617.55 | 14.54 ms | 583.47 | 873.87 ms | 9.6x | 60.1x |
| 1024 | 3,952.79 | 20.72 ms | 603.62 | 1.66 s | 6.5x | 80.1x |

## Routing-correctness checks

- 880 prompts in SPEED-Bench

| Concurrency | XDP avg ms | XDP p99 ms | XDP RPS | vLLM-SR avg ms | vLLM-SR p99 ms | vLLM-SR RPS | XSR/VSR routing agreement |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.457 | 3.465 | 1,704.99 | 2.558 | 15.248 | 388.12 | 100.00% (880/880) |
| 4 | 0.862 | 5.458 | 2,946.03 | 5.408 | 29.312 | 733.42 | 100.00% (880/880) |
| 8 | 1.521 | 8.748 | 3,224.69 | 10.128 | 47.647 | 782.91 | 100.00% (880/880) |
| 16 | 2.978 | 15.817 | 3,160.88 | 19.678 | 90.214 | 802.91 | 100.00% (880/880) |

## Raw reports

- Performance: `results/routing-performance/routing_performance_{1, 2, 4, 8, 10, 16, 32, 64, 96, 128, 144, 160, 176, 192, 256, 512, 1024}.md`
- Correctness: `results/routing-correctness/routing_correctness_benchmark_concurrency_{1, 4, 8, 16}.md`
