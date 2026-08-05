# High-Performance wrk Benchmark Report

- Timestamp: `Wed Aug  5 04:34:32 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `16`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     0.88ms  452.40us  16.06ms   94.47%
    Req/Sec     4.61k   162.35     5.77k    78.25%
  183413 requests in 10.01s, 28.51MB read
Requests/sec:  18317.89
Transfer/sec:      2.85MB
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     5.11ms    1.76ms   9.67ms   67.18%
    Req/Sec   488.50      5.97   494.00     75.00%
  195 requests in 10.02s, 84.74KB read
Requests/sec:     19.46
Transfer/sec:      8.46KB
```
