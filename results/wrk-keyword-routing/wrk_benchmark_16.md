# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 13 23:01:27 PDT 2026`
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
    Latency     4.97ms    1.35ms  47.02ms   70.07%
    Req/Sec   799.75     84.75     0.97k    56.92%
  95547 requests in 30.01s, 12.48MB read
Requests/sec:   3183.63
Transfer/sec:    425.68KB
[Lua] backend markers: coding=30399 math=29480 others=35668 unknown=0
[Lua] expected routes: coding=35897 math=37039 others=22611 unknown=0
[Lua] aggregate route agreement: 0.863345 (82490/95547); fifo_matches=70107 fifo_mismatches=25440
[Lua] warning: backend marker agreement is low; verify the target has reloaded policy config with distinct backend endpoints
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    17.01ms    4.06ms  53.27ms   74.24%
    Req/Sec   235.65     34.70   320.00     61.67%
  28172 requests in 30.02s, 10.32MB read
Requests/sec:    938.53
Transfer/sec:    352.00KB
[Lua] backend markers: coding=9592 math=9532 others=9048 unknown=0
[Lua] expected routes: coding=10680 math=10858 others=6634 unknown=0
[Lua] aggregate route agreement: 0.914312 (25758/28172); fifo_matches=20555 fifo_mismatches=7617
```
