# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 13 22:57:21 PDT 2026`
- Tool: `wrk`
- Threads: `2`
- Connections: `2`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   759.91us  476.25us  15.68ms   84.89%
    Req/Sec     1.32k   184.98     1.60k    89.50%
  79061 requests in 30.01s, 10.34MB read
Requests/sec:   2634.17
Transfer/sec:    352.68KB
[Lua] backend markers: coding=25079 math=24418 others=29564 unknown=0
[Lua] expected routes: coding=29663 math=30664 others=18734 unknown=0
[Lua] aggregate route agreement: 0.863017 (68231/79061); fifo_matches=58001 fifo_mismatches=21060
[Lua] warning: backend marker agreement is low; verify the target has reloaded policy config with distinct backend endpoints
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.73ms    0.87ms   8.02ms   66.46%
    Req/Sec   362.61     29.00   430.00     63.17%
  21674 requests in 30.02s, 7.94MB read
Requests/sec:    722.05
Transfer/sec:    270.69KB
[Lua] backend markers: coding=7274 math=7380 others=7020 unknown=0
[Lua] expected routes: coding=8161 math=8378 others=5135 unknown=0
[Lua] aggregate route agreement: 0.913029 (19789/21674); fifo_matches=15811 fifo_mismatches=5863
```
