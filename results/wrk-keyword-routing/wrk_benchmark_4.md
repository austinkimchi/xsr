# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 13 22:58:23 PDT 2026`
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
    Latency     1.44ms  525.46us   4.13ms   66.83%
    Req/Sec   680.28     74.11     0.91k    56.08%
  81339 requests in 30.04s, 10.61MB read
Requests/sec:   2707.81
Transfer/sec:    361.84KB
[Lua] backend markers: coding=25839 math=25160 others=30340 unknown=0
[Lua] expected routes: coding=30532 math=31572 others=19235 unknown=0
[Lua] aggregate route agreement: 0.863473 (70234/81339); fifo_matches=59694 fifo_mismatches=21645
[Lua] warning: backend marker agreement is low; verify the target has reloaded policy config with distinct backend endpoints
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.41ms    1.51ms  17.78ms   68.89%
    Req/Sec   226.01     33.44   303.00     60.08%
  27022 requests in 30.02s, 9.89MB read
Requests/sec:    900.07
Transfer/sec:    337.37KB
[Lua] backend markers: coding=9102 math=9184 others=8736 unknown=0
[Lua] expected routes: coding=10198 math=10430 others=6394 unknown=0
[Lua] aggregate route agreement: 0.913330 (24680/27022); fifo_matches=19718 fifo_mismatches=7304
```
