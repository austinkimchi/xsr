# XDP vs. vLLM-SR Benchmark Summary

This summary records the controlled `wrk` benchmark sweep run on August 13,
2026. Every point used a 30-second run, the shared Jaccard trigram keyword
policy, and the same prompt corpus. Both the XDP-assisted routing proxy and
vLLM-SR were driven from `ns1` across the same `veth1 -> veth0` client path to
`10.10.0.1`; they were run separately for each concurrency value.

## Summary

| Concurrency | XDP RPS | XDP avg latency | vLLM-SR RPS | vLLM-SR avg latency | XDP throughput speedup | XDP latency speedup |
| :---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,532.68 | 379.74 us | 403.48 | 2.45 ms | 6.3x | 6.5x |
| 2 | 2,634.17 | 759.91 us | 722.05 | 2.73 ms | 3.6x | 3.6x |
| 4 | 2,707.81 | 1.44 ms | 900.07 | 4.41 ms | 3.0x | 3.1x |
| 8 | 3,008.35 | 2.69 ms | 931.60 | 8.54 ms | 3.2x | 3.2x |
| 10 | 3,213.10 | 2.41 ms | 938.86 | 8.48 ms | 3.4x | 3.5x |
| 16 | 3,183.63 | 4.97 ms | 938.53 | 17.01 ms | 3.4x | 3.4x |
| 32 | 3,271.82 | 9.73 ms | 934.12 | 34.21 ms | 3.5x | 3.5x |
| 64 | 3,388.82 | 18.80 ms | 932.11 | 68.55 ms | 3.6x | 3.6x |
| 96 | 3,121.42 | 30.78 ms | 922.89 | 103.88 ms | 3.4x | 3.4x |

Speedups are calculated as `XDP / vLLM-SR` for throughput and
`vLLM-SR / XDP` for average latency.

## Observations

- XDP sustained 2,532.68–3,388.82 RPS across the sweep; it peaked at
  concurrency 64.
- vLLM-SR saturated near 930 RPS from concurrency 8 onward, while its average
  latency rose from 8.54 ms at concurrency 8 to 103.88 ms at concurrency 96.
- XDP retained a 3.0x–6.3x throughput advantage and a 3.1x–6.5x average
  latency advantage in these runs.

## Raw Reports

The timestamped reports retain the full `wrk` output, request counts, backend
marker totals, and route-agreement measurements.

| Concurrency | Report |
| :---: | :--- |
| 1 | `results/wrk-keyword-routing/wrk_benchmark_1.md` |
| 2 | `results/wrk-keyword-routing/wrk_benchmark_2.md` |
| 4 | `results/wrk-keyword-routing/wrk_benchmark_4.md` |
| 8 | `results/wrk-keyword-routing/wrk_benchmark_8.md` |
| 10 | `results/wrk-keyword-routing/wrk_benchmark_10.md` |
| 16 | `results/wrk-keyword-routing/wrk_benchmark_16.md` |
| 32 | `results/wrk-keyword-routing/wrk_benchmark_32.md` |
| 64 | `results/wrk-keyword-routing/wrk_benchmark_64.md` |
| 96 | `results/wrk-keyword-routing/wrk_benchmark_96.md` |
