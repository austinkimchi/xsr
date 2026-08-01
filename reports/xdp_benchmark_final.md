# XDP Routing Benchmark
- Kernel: 6.8.0-136-generic
- CPU count: 16

## Control Result

| Dataset | Mode | p99 ms | max ms | RPS | CPU % |
| --- | --- | --- | ---: | ---: | ---: |
| supralabs | direct-netns | 4.107 | 10.306 | 3369.013 | 20.333 |
| empero-tasklist | direct-netns | 5.043 | 11.170 | 3382.695 | 15.942 |
| speed-bench | direct-netns |3.876 | 12.030 | 3444.037 | 15.028 |
| routerbench | direct-netns | 4.891 | 8.602 | 4469.215 | 14.790 |
| synthetic-pld | direct-netns | 4.326 | 9.456 | 3447.153 | 16.211 |

## Dataset: SupraLabs/Prompt-Routing-Dataset

- Requested cases: 800 (0 skipped rows)
- Unique rows: 992

| Mode    | Accuracy | p99 ms   | RPS     | CPU %  |
| ---     | ---:     | ---:     | ---:    | ---:   |
| direct  | n/a      | 7.018    | 560.133 | 4.505  |
| xdp     | 0.9800   | 6.344    | 688.736 | 5.306  |
| vllm-sr | 0.8100   | 1721.407 | 14.011  | 90.923 |

## Dataset: empero-ai/tasklist-qwen3.5-9B-7500x-unfiltered

- Requested cases: 800/2000 (0 skipped rows)
- Unique rows: 2000

| Mode   | Accuracy | p99 ms   |  RPS    | CPU %  |
| ---    | ---:     | ---:     | ---:    | ---:   |
| direct | n/a      | 5.746    | 737.673 | 3.900  |
| xdp    | 0.7650   | 3.575    | 706.283 | 5.524  |
| vllm-sr| 0.8825   | 4173.893 | 5.567   | 90.503 |


## Dataset: nvidia/SPEED-Bench

- Requested cases: 800 (0 skipped rows)
- Unique rows: 880

| Mode     | Accuracy | p99 ms   | RPS     | CPU %  |
| ---      | ---:     | ---:     | ---:    | ---:   |
| direct   | n/a      | 6.133    | 704.654 | 6.069  |
| xdp      | 0.6300   | 3.768    | 752.088 | 6.114  |
| vllm-sr  | 0.4050   | 8047.069 | 5.187   | 90.270 |
