# XDP Routing Benchmark
- Kernel: 6.8.0-136-generic
- CPU count: 16

## Control Result

#### direct-netns Control (Default Route)
| Dataset          | p50 ms | p99 ms | max ms | RPS      | CPU %  |
| ---              | ---    | ---    | ---:   | ---:     | ---:   |
| supralabs        | 2.218  | 4.107  | 10.306 | 3369.013 | 20.333 |
| empero-tasklist  | 2.179  | 5.043  | 11.170 | 3382.695 | 15.942 |
| speed-bench      | 2.151  | 3.876  | 12.030 | 3444.037 | 15.028 |

#### VLLM SR Control (Default Route)
| Dataset         | p50 ms  | p99 ms  | max ms  | RPS       | CPU %    |
| ---             | ---     | ---     |  ---:   | ---:      | ---:     |
|supralabs        | 2.372   | 6.752   |  9.026  | 3045.007  |  23.990% |
|empero-tasklist  | 2.486   | 4.908   |  7.816  | 3024.388  |  24.814% |
|speed-bench      | 2.391   | 4.832   |  7.870  | 3061.773  |  24.242% |
|routerbench      | 2.454   | 4.757   |  8.480  | 3049.883  |  24.876% |
|synthetic-pld    | 2.368   | 4.365   |  13.717 | 3224.154  |  24.934% |


## Dataset: SupraLabs/Prompt-Routing-Dataset

- Requested cases: 800 (0 skipped rows)
- Unique rows: 992

| Mode    | Accuracy |  p50 ms   | p99 ms   | RPS     | CPU %  |
| ---     | ---:     |  ---:     | ---:     | ---:    | ---:   |
| direct  | n/a      |  4.237    | 7.018    | 560.133 | 4.505  |
| xdp     | 0.9800   |  1.417    | 6.344    | 688.736 | 5.306  |
| vllm-sr | 0.8100   |  490.933  | 1721.407 | 14.011  | 90.923 |

## Dataset: empero-ai/tasklist-qwen3.5-9B-7500x-unfiltered

- Requested cases: 800 (0 skipped rows)
- Unique rows: 2000

| Mode   | Accuracy |  p50 ms  | p99 ms   |  RPS    | CPU %  |
| ---    | ---:     |  ---:    | ---:     | ---:    | ---:   |
| direct | n/a      |  2.667   | 5.746    | 737.673 | 3.900  |
| xdp    | 0.7650   |  1.542   | 3.575    | 706.283 | 5.524  |
| vllm-sr| 0.8825   |  1268.94 | 4173.893 | 5.567   | 90.503 |


## Dataset: nvidia/SPEED-Bench

- Requested cases: 800 (0 skipped rows)
- Unique rows: 880

| Mode     | Accuracy | p50 ms  | p99 ms   | RPS     | CPU %  |
| ---      | ---:     | ---:    | ---:     | ---:    | ---:   |
| direct   | n/a      | 3.278   | 6.133    | 704.654 | 6.069  |
| xdp      | 0.6300   | 1.970   | 3.768    | 752.088 | 6.114  |
| vllm-sr  | 0.4050   | 572.230 | 8047.069 | 5.187   | 90.270 |


## Summary & Observations
XDP versus vllm-sr across benchmarks:
| Dataset           |   p50 speedup |   p90 speedup | RPS speedup   | Geometric mean    |
| ---               |   ---         |   ---         | ---           | ---               |
| supralabs         |   346.34x     |   271.34 x    | 49.16x        | 166.55x           |
| empero-tasklist   |   822.92x     |   1167.52 x   | 126.83x       | 495.80x           |
| speed-bench       |   290.51x     |   2135.63 x   | 144.98x       | 448.07x           |

XDP and vllm-sr accuracy comparison:
| Dataset          | XDP accuracy   | vllm-sr accuracy  |
| ---              | ---            | ---               |
| supralabs        | 0.9800         | 0.8100            |
| empero-tasklist  | 0.7650         | 0.8825            |
| speed-bench      | 0.6300         | 0.4050            |