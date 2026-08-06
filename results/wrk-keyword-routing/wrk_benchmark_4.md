# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 05:38:09 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `4`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   251.15us  186.17us   3.91ms   91.10%
    Req/Sec     4.15k   218.80     4.48k    93.56%
  167059 requests in 10.10s, 25.97MB read
Requests/sec:  16540.97
Transfer/sec:      2.57MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.30ms  377.55us   7.18ms   82.26%
    Req/Sec   434.38     22.17   474.00     79.50%
  17300 requests in 10.01s, 6.76MB read
Requests/sec:   1728.99
Transfer/sec:    692.31KB
```
