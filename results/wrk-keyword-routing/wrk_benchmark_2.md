# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 05:39:11 PM PDT 2026`
- Tool: `wrk`
- Threads: `2`
- Connections: `2`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   136.79us  121.26us   3.37ms   92.21%
    Req/Sec     7.80k   173.62     8.24k    72.28%
  156773 requests in 10.10s, 24.37MB read
Requests/sec:  15522.56
Transfer/sec:      2.41MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.57ms  266.29us   6.06ms   88.17%
    Req/Sec   638.47     33.24   690.00     90.50%
  12714 requests in 10.00s, 4.97MB read
Requests/sec:   1270.80
Transfer/sec:    508.79KB
```
