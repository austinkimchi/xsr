# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 05:39:56 PM PDT 2026`
- Tool: `wrk`
- Threads: `1`
- Connections: `1`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    80.63us  132.36us   3.32ms   95.42%
    Req/Sec    14.46k     0.88k   15.30k    95.05%
  145272 requests in 10.10s, 22.58MB read
Requests/sec:  14383.61
Transfer/sec:      2.24MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.37ms  287.12us   5.65ms   90.42%
    Req/Sec   729.99     35.97   800.00     63.00%
  7268 requests in 10.00s, 2.84MB read
Requests/sec:    726.69
Transfer/sec:    290.95KB
```
