# XDP vs. vLLM-SR benchmark summary

- Ran on August 25, 2026 at 10:11:18 PM PDT
- Duration of test: 60s per concurrency level
- Routing path: XSR (SOCKMAP)

| Concurrency | XSR requests/s | XSR average latency | vLLM-SR requests/s | vLLM-SR average latency | XSR throughput advantage | XSR latency advantage |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,696.12 | 364.83 us | 345.34 | 2.88 ms | 7.8x | 7.9x |
| 2 | 4,566.77 | 431.12 us | 525.67 | 3.79 ms | 8.7x | 8.8x |
| 4 | 7,462.11 | 529.62 us | 527.13 | 7.56 ms | 14.2x | 14.3x |
| 8 | 9,500.04 | 813.99 us | 637.96 | 12.52 ms | 14.9x | 15.4x |
| 16 | 8,027.74 | 1.56 ms | 552.72 | 28.92 ms | 14.5x | 18.5x |
| 32 | 8,174.93 | 2.50 ms | 529.38 | 60.41 ms | 15.4x | 24.2x |
| 64 | 9,148.30 | 3.97 ms | 602.20 | 106.19 ms | 15.2x | 26.7x |
| 96 | 8,176.67 | 6.38 ms | 564.55 | 169.80 ms | 14.5x | 26.6x |
| 128 | 8,096.84 | 8.41 ms | 537.28 | 237.68 ms | 15.1x | 28.3x |
| 160 | 9,708.88 | 8.67 ms | 569.02 | 280.48 ms | 17.1x | 32.4x |
| 192 | 8,142.09 | 12.28 ms | 570.16 | 335.88 ms | 14.3x | 27.4x |
| 256 | 8,061.25 | 16.36 ms | 533.60 | 477.35 ms | 15.1x | 29.2x |
| 512 | 9,367.62 | 25.43 ms | 573.79 | 884.79 ms | 16.3x | 34.8x |

## Detailed performance summary

Average Req/Sec is the per-thread average reported by wrk.

| Concurrency | XSR avg latency | XSR avg Req/Sec | XSR p50 latency | XSR p95 latency | XSR p99 latency | VSR avg latency | VSR avg Req/Sec | VSR p50 latency | VSR p95 latency | VSR p99 latency |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 364.83 us | 2,710.00 | 345.00 us | 702.00 us | 854.00 us | 2.88 ms | 346.84 | 2767.00 us | 4655.00 us | 5365.00 us |
| 2 | 431.12 us | 2,300.00 | 406.00 us | 840.00 us | 1028.00 us | 3.79 ms | 263.99 | 3688.00 us | 6249.00 us | 7564.00 us |
| 4 | 529.62 us | 1,870.00 | 497.00 us | 1046.00 us | 1271.00 us | 7.56 ms | 132.30 | 7442.00 us | 11662.00 us | 13537.00 us |
| 8 | 813.99 us | 2,390.00 | 767.00 us | 1521.00 us | 1811.00 us | 12.52 ms | 160.07 | 12283.00 us | 18578.00 us | 21407.00 us |
| 16 | 1.56 ms | 2,020.00 | 1510.00 us | 2833.00 us | 3528.00 us | 28.92 ms | 138.69 | 28221.00 us | 39941.00 us | 45494.00 us |
| 32 | 2.50 ms | 2,050.00 | 2367.00 us | 4760.00 us | 5982.00 us | 60.41 ms | 132.84 | 58636.00 us | 80055.00 us | 92378.00 us |
| 64 | 3.97 ms | 2,300.00 | 3744.00 us | 7790.00 us | 9494.00 us | 106.19 ms | 151.14 | 104895.00 us | 142568.00 us | 164047.00 us |
| 96 | 6.38 ms | 2,060.00 | 6137.00 us | 12348.00 us | 14590.00 us | 169.80 ms | 142.27 | 167268.00 us | 219483.00 us | 234017.00 us |
| 128 | 8.41 ms | 2,040.00 | 8134.00 us | 16104.00 us | 19033.00 us | 237.68 ms | 135.41 | 227242.00 us | 284522.00 us | 311126.00 us |
| 160 | 8.67 ms | 2,440.00 | 8394.00 us | 16756.00 us | 19484.00 us | 280.48 ms | 147.23 | 278529.00 us | 353220.00 us | 371863.00 us |
| 192 | 12.28 ms | 2,050.00 | 12005.00 us | 23502.00 us | 27238.00 us | 335.88 ms | 143.17 | 334598.00 us | 428333.00 us | 453376.00 us |
| 256 | 16.36 ms | 2,030.00 | 16058.00 us | 31531.00 us | 35720.00 us | 477.35 ms | 135.67 | 465961.00 us | 556838.00 us | 582102.00 us |
| 512 | 25.43 ms | 2,360.00 | 24846.00 us | 49926.00 us | 57732.00 us | 884.79 ms | 146.59 | 883841.00 us | 1045741.00 us | 1090078.00 us |

## Routing-correctness checks

- 880 prompts in SPEED-Bench

| Concurrency | XDP avg ms | XDP p99 ms | XDP RPS | vLLM-SR avg ms | vLLM-SR p99 ms | vLLM-SR RPS | XSR/VSR routing agreement |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.457 | 3.465 | 1,704.99 | 2.558 | 15.248 | 388.12 | 100.00% (880/880) |
| 4 | 0.862 | 5.458 | 2,946.03 | 5.408 | 29.312 | 733.42 | 100.00% (880/880) |
| 8 | 1.521 | 8.748 | 3,224.69 | 10.128 | 47.647 | 782.91 | 100.00% (880/880) |
| 16 | 2.978 | 15.817 | 3,160.88 | 19.678 | 90.214 | 802.91 | 100.00% (880/880) |

## Raw reports

- Performance: `results/routing-performance/routing_performance_{1, 2, 4, 8, 16, 32, 64, 96, 128, 160, 192, 256, 512}.md`
- Correctness: `results/routing-correctness/routing_correctness_benchmark_concurrency_{1, 4, 8, 16}.md`
