# High-Performance wrk Benchmark Report

- Timestamp: `Wed Aug  5 04:33:26 PM PDT 2026`
- Tool: `wrk`
- Threads: `1`
- Connections: `1`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    82.50us  124.12us   4.19ms   95.00%
    Req/Sec    13.75k     0.91k   14.51k    94.06%
  138217 requests in 10.10s, 21.49MB read
Requests/sec:  13685.10
Transfer/sec:      2.13MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.32ms  257.19us   6.48ms   89.78%
    Req/Sec   756.85     36.61   828.00     78.00%
  7539 requests in 10.01s, 2.95MB read
Requests/sec:    753.32
Transfer/sec:    301.51KB
```
