# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 05:32:16 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `32`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.59ms  576.40us  18.72ms   92.83%
    Req/Sec     5.10k   305.20     6.45k    89.75%
  203008 requests in 10.01s, 31.56MB read
Requests/sec:  20274.49
Transfer/sec:      3.15MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    15.51ms    7.98ms  46.51ms   64.58%
    Req/Sec   524.59     83.06   720.00     66.00%
  20898 requests in 10.01s, 8.17MB read
Requests/sec:   2088.19
Transfer/sec:    836.25KB
```
