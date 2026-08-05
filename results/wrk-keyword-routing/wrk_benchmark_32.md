# High-Performance wrk Benchmark Report

- Timestamp: `Wed Aug  5 04:34:53 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `32`
- Duration: `10s`

## [1/2] XDP Route (via netns)
```
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
[Lua] Loaded 150 prompts from tests/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     0.86ms  462.55us  18.58ms   93.40%
    Req/Sec     6.25k     2.29k   14.95k    65.12%
  187238 requests in 10.10s, 29.11MB read
Requests/sec:  18538.90
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
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     5.71ms    2.98ms  17.66ms   60.77%
    Req/Sec   452.50     20.62   470.00     75.00%
  181 requests in 10.03s, 78.66KB read
Requests/sec:     18.05
Transfer/sec:      7.84KB
```
