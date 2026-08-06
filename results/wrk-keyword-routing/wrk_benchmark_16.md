# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 05:36:38 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `16`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     0.87ms  585.20us  17.78ms   95.91%
    Req/Sec     4.73k   404.04     9.76k    91.54%
  189346 requests in 10.10s, 29.43MB read
Requests/sec:  18747.28
Transfer/sec:      2.91MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     7.80ms    4.06ms  22.28ms   72.47%
    Req/Sec   519.36     56.69   680.00     66.00%
  20692 requests in 10.01s, 8.09MB read
Requests/sec:   2067.86
Transfer/sec:    827.43KB
```
