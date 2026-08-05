# High-Performance wrk Benchmark Report

- Timestamp: `Wed Aug  5 04:34:10 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `8`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   449.32us  257.01us   4.94ms   86.17%
    Req/Sec     4.41k   453.35     8.47k    80.10%
  176315 requests in 10.10s, 27.41MB read
Requests/sec:  17457.97
Transfer/sec:      2.71MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.48ms  581.25us   6.62ms   93.21%
    Req/Sec   708.89     94.96   790.00     91.59%
  7556 requests in 10.01s, 2.96MB read
Requests/sec:    754.76
Transfer/sec:    303.13KB
```
