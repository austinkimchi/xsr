# High-Performance wrk Benchmark Report

- Timestamp: `Wed Aug  5 04:35:35 PM PDT 2026`
- Tool: `wrk`
- Threads: `2`
- Connections: `2`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   137.09us  128.05us   4.39ms   92.46%
    Req/Sec     7.80k   698.50    13.28k    93.53%
  156026 requests in 10.10s, 24.25MB read
Requests/sec:  15449.43
Transfer/sec:      2.40MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.57ms  317.27us  11.60ms   91.32%
    Req/Sec   639.66     29.43   686.00     79.00%
  12736 requests in 10.00s, 4.98MB read
Requests/sec:   1273.11
Transfer/sec:    509.78KB
```
