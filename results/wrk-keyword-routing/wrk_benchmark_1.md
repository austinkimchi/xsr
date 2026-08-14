# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 13 22:56:20 PDT 2026`
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
    Latency   379.74us  186.80us   3.70ms   66.61%
    Req/Sec     2.54k    87.46     2.71k    83.67%
  75981 requests in 30.00s, 9.94MB read
Requests/sec:   2532.68
Transfer/sec:    339.43KB
[Lua] backend markers: coding=24091 math=23442 others=28448 unknown=0
[Lua] expected routes: coding=28505 math=29453 others=18023 unknown=0
[Lua] aggregate route agreement: 0.862795 (65556/75981); fifo_matches=55730 fifo_mismatches=20251
[Lua] warning: backend marker agreement is low; verify the target has reloaded policy config with distinct backend endpoints
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.45ms    0.90ms  13.40ms   70.77%
    Req/Sec   405.34     56.55   510.00     71.67%
  12112 requests in 30.02s, 4.44MB read
Requests/sec:    403.48
Transfer/sec:    151.38KB
[Lua] backend markers: coding=4079 math=4133 others=3900 unknown=0
[Lua] expected routes: coding=4563 math=4690 others=2859 unknown=0
[Lua] aggregate route agreement: 0.914052 (11071/12112); fifo_matches=8836 fifo_mismatches=3276
```
