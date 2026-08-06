# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:00:48 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `64`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] Routing Proxy
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:18081/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.18ms    3.23ms  38.97ms   88.03%
    Req/Sec     9.49k     5.08k   16.79k    66.75%
  378311 requests in 10.06s, 49.46MB read
Requests/sec:  37609.07
Transfer/sec:      4.92MB
[Lua] backend markers: coding=162385 math=149729 others=66197 unknown=0
[Lua] expected routes: coding=141900 math=146575 others=89836 unknown=0
[Lua] aggregate route agreement: 0.937514 (354672/378311); fifo_matches=321570 fifo_mismatches=56741
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    69.07ms   14.14ms 181.62ms   83.86%
    Req/Sec   231.93     42.65   333.00     64.00%
  9244 requests in 10.02s, 3.40MB read
Requests/sec:    922.95
Transfer/sec:    347.33KB
[Lua] backend markers: coding=3199 math=3229 others=2816 unknown=0
[Lua] expected routes: coding=3507 math=3641 others=2096 unknown=0
[Lua] aggregate route agreement: 0.922112 (8524/9244); fifo_matches=6778 fifo_mismatches=2466
```
