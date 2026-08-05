# High-Performance wrk Benchmark Report

- Timestamp: `Wed Aug  5 04:33:48 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `4`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   221.82us  159.48us   4.39ms   90.27%
    Req/Sec     4.66k   105.21     4.87k    71.78%
  187257 requests in 10.10s, 29.11MB read
Requests/sec:  18540.85
Transfer/sec:      2.88MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.35ms  580.31us  12.57ms   65.87%
    Req/Sec   426.84     87.71   616.00     74.00%
  17006 requests in 10.01s, 6.65MB read
Requests/sec:   1699.32
Transfer/sec:    680.03KB
```
