# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug  6 01:08:20 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `64`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     3.18ms  476.73us   8.49ms   68.92%
    Req/Sec     4.98k   428.01     9.01k    87.35%
  595564 requests in 30.10s, 78.07MB read
Requests/sec:  19786.41
Transfer/sec:      2.59MB
[Lua] backend markers: coding=255639 math=235743 others=104182 unknown=0
[Lua] expected routes: coding=223396 math=230782 others=141386 unknown=0
[Lua] aggregate route agreement: 0.937531 (558360/595564); fifo_matches=506245 fifo_mismatches=89319
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    85.51ms   16.22ms 284.91ms   81.92%
    Req/Sec   187.61     30.99   330.00     71.00%
  22440 requests in 30.04s, 8.22MB read
Requests/sec:    747.11
Transfer/sec:    280.28KB
[Lua] backend markers: coding=7679 math=7585 others=7176 unknown=0
[Lua] expected routes: coding=8525 math=8647 others=5268 unknown=0
[Lua] aggregate route agreement: 0.914973 (20532/22440); fifo_matches=16378 fifo_mismatches=6062
```
