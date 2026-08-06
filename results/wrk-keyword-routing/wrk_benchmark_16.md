# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:50:38 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `16`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   603.96us  393.40us  11.22ms   98.13%
    Req/Sec     6.50k   540.45    15.61k    92.77%
  259485 requests in 10.10s, 33.91MB read
Requests/sec:  25693.47
Transfer/sec:      3.36MB
[Lua] backend markers: coding=111402 math=102735 others=45348 unknown=0
[Lua] expected routes: coding=97370 math=100574 others=61541 unknown=0
[Lua] aggregate route agreement: 0.937596 (243292/259485); fifo_matches=220584 fifo_mismatches=38901
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    17.21ms    4.11ms  62.55ms   75.05%
    Req/Sec   232.76     35.77   310.00     62.50%
  9278 requests in 10.01s, 3.41MB read
Requests/sec:    927.17
Transfer/sec:    348.89KB
[Lua] backend markers: coding=3199 math=3251 others=2828 unknown=0
[Lua] expected routes: coding=3515 math=3663 others=2100 unknown=0
[Lua] aggregate route agreement: 0.921535 (8550/9278); fifo_matches=6802 fifo_mismatches=2476
```
