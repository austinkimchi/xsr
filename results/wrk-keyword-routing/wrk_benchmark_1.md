# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug  6 01:01:11 PM PDT 2026`
- Tool: `wrk`
- Threads: `1`
- Connections: `1`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   116.25us   44.57us   3.16ms   96.26%
    Req/Sec     7.51k   259.51     8.11k    70.76%
  224968 requests in 30.10s, 29.55MB read
Requests/sec:   7474.02
Transfer/sec:      0.98MB
[Lua] backend markers: coding=96571 math=89038 others=39359 unknown=0
[Lua] expected routes: coding=84390 math=87163 others=53415 unknown=0
[Lua] aggregate route agreement: 0.937520 (210912/224968); fifo_matches=191227 fifo_mismatches=33741
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://127.0.0.1:8899/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.37ms  752.94us   7.25ms   65.28%
    Req/Sec   416.70     37.91   505.00     69.67%
  12449 requests in 30.01s, 4.56MB read
Requests/sec:    414.81
Transfer/sec:    155.57KB
[Lua] backend markers: coding=4159 math=4262 others=4028 unknown=0
[Lua] expected routes: coding=4669 math=4830 others=2950 unknown=0
[Lua] aggregate route agreement: 0.913407 (11371/12449); fifo_matches=9084 fifo_mismatches=3365
```
