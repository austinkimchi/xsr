# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 05:05:36 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `8`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   414.00us  244.78us   5.09ms   87.20%
    Req/Sec     4.79k   536.04     9.04k    84.08%
  191669 requests in 10.10s, 29.79MB read
Requests/sec:  18978.30
Transfer/sec:      2.95MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.71ms  505.08us  10.55ms   93.08%
    Req/Sec   603.40     45.01   686.00     69.12%
  12260 requests in 10.01s, 4.80MB read
Requests/sec:   1224.75
Transfer/sec:    490.86KB
```
