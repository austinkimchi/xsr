# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 13 23:00:26 PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `10`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.41ms    1.09ms  15.32ms   80.41%
    Req/Sec   808.83    117.76     2.56k    74.02%
  96691 requests in 30.09s, 12.63MB read
Requests/sec:   3213.10
Transfer/sec:    429.64KB
[Lua] backend markers: coding=30703 math=29876 others=36112 unknown=0
[Lua] expected routes: coding=36290 math=37510 others=22891 unknown=0
[Lua] aggregate route agreement: 0.863265 (83470/96691); fifo_matches=70947 fifo_mismatches=25744
[Lua] warning: backend marker agreement is low; verify the target has reloaded policy config with distinct backend endpoints
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.48ms    2.19ms  22.98ms   69.63%
    Req/Sec   235.73     31.82   313.00     55.33%
  28183 requests in 30.02s, 10.32MB read
Requests/sec:    938.86
Transfer/sec:    352.13KB
[Lua] backend markers: coding=9589 math=9546 others=9048 unknown=0
[Lua] expected routes: coding=10678 math=10869 others=6636 unknown=0
[Lua] aggregate route agreement: 0.914416 (25771/28183); fifo_matches=20562 fifo_mismatches=7621
```
