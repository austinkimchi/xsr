# Keyword Routing Benchmark

- Dataset: `SupraLabs/Prompt-Routing-Dataset`
- Total rows: 992
- Selected prompts: coding=50, math=50, others=50
- Filtered rows: embedded_quote=60, duplicate_prompt=0, missing_prompt=0
- Policy: case_sensitive=False; keywords=13

## Control Result

| Mode | Requests | avg ms | p99 ms | RPS | Host CPU % | Sampled CPU % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| direct-netns | 150 | 0.541 | 0.828 | 797.739 | 10.403 | n/a |

## Results

| Mode | Requests | Route agreement | avg ms | p99 ms | RPS | Host CPU % | Sampled CPU % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| xdp | 150 | 1.0000 | 0.400 | 1.391 | 1104.404 | 11.628 | 23.800 |
| vllm-sr | 150 | 1.0000 | 1.989 | 3.061 | 493.034 | 15.222 | 0.810 |

## Route Counts

| Mode | coding | math | others |
| --- | ---: | ---: | ---: |
| xdp | 50 | 50 | 50 |
| vllm-sr | 50 | 50 | 50 |

## Comparison

| Metric | avg speedup | p99 speedup | RPS speedup |
| --- | ---: | ---: | ---: |
| XDP vs vLLM-SR | 4.98x | 2.20x | 2.24x |

- Route agreement delta, XDP minus vLLM-SR: 0.0000
- Average latency delta, XDP minus vLLM-SR: -1.589 ms
- p99 latency delta, XDP minus vLLM-SR: -1.670 ms

Note: Sampled CPU % for XDP measures the userspace logger process (xdp_router) handling XDP_DEBUG ring-buffer polling. In production without debug logging, the CPU usage is negligible.
