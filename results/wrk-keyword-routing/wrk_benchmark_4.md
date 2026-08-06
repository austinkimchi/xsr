# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug  6 01:03:14 PM PDT 2026`
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
    Latency   201.94us   58.72us   3.97ms   73.93%
    Req/Sec     4.38k   170.77     4.79k    82.81%
  525104 requests in 30.10s, 68.79MB read
Requests/sec:  17445.58
Transfer/sec:      2.29MB
[Lua] backend markers: coding=225385 math=207860 others=91859 unknown=0
[Lua] expected routes: coding=196956 math=203487 others=124661 unknown=0
[Lua] aggregate route agreement: 0.937532 (492302/525104); fifo_matches=446356 fifo_mismatches=78748
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.37ms    1.42ms  11.81ms   66.89%
    Req/Sec   227.57     30.32   300.00     61.08%
  27212 requests in 30.02s, 9.97MB read
Requests/sec:    906.42
Transfer/sec:    339.96KB
[Lua] backend markers: coding=9279 math=9197 others=8736 unknown=0
[Lua] expected routes: coding=10323 math=10482 others=6407 unknown=0
[Lua] aggregate route agreement: 0.914413 (24883/27212); fifo_matches=19853 fifo_mismatches=7359
```
