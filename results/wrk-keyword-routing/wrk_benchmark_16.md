# High-Performance wrk Benchmark Results

- Timestamp: `Fri Aug 14 04:18:30 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `16`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.64ms    1.21ms  42.43ms   68.48%
    Req/Sec     0.86k    74.67     1.02k    65.17%
  102364 requests in 30.02s, 13.36MB read
Requests/sec:   3410.32
Transfer/sec:    455.90KB
[Lua] backend markers: coding=34239 math=34585 others=33540 unknown=0
[Lua] expected routes: coding=38437 math=39693 others=24234 unknown=0
[Lua] aggregate route agreement: 0.909089 (93058/102364); fifo_matches=74247 fifo_mismatches=28117
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    16.96ms    3.99ms  45.79ms   73.59%
    Req/Sec   236.29     34.36   323.00     63.50%
  28246 requests in 30.01s, 10.35MB read
Requests/sec:    941.10
Transfer/sec:    353.03KB
[Lua] backend markers: coding=9599 math=9599 others=9048 unknown=0
[Lua] expected routes: coding=10690 math=10915 others=6641 unknown=0
[Lua] aggregate route agreement: 0.914784 (25839/28246); fifo_matches=20614 fifo_mismatches=7632
```
