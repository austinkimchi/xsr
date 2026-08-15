# High-Performance wrk Benchmark Results

- Timestamp: `Fri Aug 14 04:15:35 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `4`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.45ms  525.26us   4.31ms   67.54%
    Req/Sec   677.26     75.93   848.00     54.67%
  80991 requests in 30.04s, 10.56MB read
Requests/sec:   2696.18
Transfer/sec:    360.14KB
[Lua] backend markers: coding=27177 math=27270 others=26544 unknown=0
[Lua] expected routes: coding=30473 math=31342 others=19176 unknown=0
[Lua] aggregate route agreement: 0.909027 (73623/80991); fifo_matches=58738 fifo_mismatches=22253
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.35ms    1.44ms  13.26ms   67.18%
    Req/Sec   228.83     30.24   300.00     64.08%
  27359 requests in 30.02s, 10.02MB read
Requests/sec:    911.46
Transfer/sec:    341.99KB
[Lua] backend markers: coding=9279 math=9344 others=8736 unknown=0
[Lua] expected routes: coding=10335 math=10603 others=6421 unknown=0
[Lua] aggregate route agreement: 0.915384 (25044/27359); fifo_matches=19974 fifo_mismatches=7385
```
