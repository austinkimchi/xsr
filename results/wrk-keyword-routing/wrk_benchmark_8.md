# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 05:37:27 PM PDT 2026`
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
    Latency   457.28us  258.19us   3.97ms   85.44%
    Req/Sec     4.33k   472.36     8.24k    83.33%
  173172 requests in 10.10s, 26.92MB read
Requests/sec:  17146.39
Transfer/sec:      2.67MB
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
    Latency     3.69ms    1.54ms  13.78ms   82.52%
    Req/Sec   547.63     57.04   660.00     56.00%
  21819 requests in 10.01s, 8.53MB read
Requests/sec:   2179.64
Transfer/sec:      0.85MB
```
