# Keyword Routing Benchmark

- Dataset: `SupraLabs/Prompt-Routing-Dataset, empero-ai/tasklist-qwen3.5-9B-7500x-unfiltered, mayankthakur/synthetic-pld-benchmark`
- Total rows: 3032
- Selected prompts: coding=789, math=570, others=1369
- Filtered rows: embedded_quote=303, duplicate_prompt=1, missing_prompt=0
- Policy: case_sensitive=False; keywords=13
- Concurrency: 8

## Dataset Mix

| Source | Scanned | coding | math | others |
| --- | ---: | ---: | ---: | ---: |
| `SupraLabs/Prompt-Routing-Dataset` | 992 | 194 | 81 | 635 |
| `empero-ai/tasklist-qwen3.5-9B-7500x-unfiltered` | 2000 | 584 | 484 | 710 |
| `mayankthakur/synthetic-pld-benchmark` | 40 | 11 | 5 | 24 |

## Control Result

| Mode | Requests | avg ms | p99 ms | RPS | Host CPU % | Sampled CPU % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| direct-netns | 2728 | 1.548 | 4.624 | 3712.490 | 13.581 | n/a |

## Results

| Mode | Requests | Reference-label agreement | avg ms | p99 ms | RPS | Host CPU % | Sampled CPU % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| xdp | 2728 | 1.0000 | 2.440 | 9.159 | 2695.873 | 12.075 | 5.500 |
| vllm-sr | 2728 | 1.0000 | 6.965 | 13.855 | 1140.245 | 34.485 | 0.920 |

## XSR vs VSR Routing Agreement

XSR ↔ VSR agreement: 2728/2728 (100.00%)

```text
             VSR
           code math other
XSR code    789    0     0
    math      0  570     0
    other     0    0  1369
```

## Route Counts

| Mode | coding | math | others |
| --- | ---: | ---: | ---: |
| xdp | 789 | 570 | 1369 |
| vllm-sr | 789 | 570 | 1369 |

## Comparison

| Metric | avg speedup | p99 speedup | RPS speedup |
| --- | ---: | ---: | ---: |
| XDP vs vLLM-SR | 2.85x | 1.51x | 2.36x |

- Reference-label agreement delta, XDP minus vLLM-SR: 0.0000
- Average latency delta, XDP minus vLLM-SR: -4.525 ms
- p99 latency delta, XDP minus vLLM-SR: -4.697 ms

Note: Sampled CPU % for XDP measures the userspace logger process (xdp_router) handling XDP_DEBUG ring-buffer polling. In production without debug logging, the CPU usage is negligible.
