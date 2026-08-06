# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 10:57:18 PM PDT 2026`
- Tool: `wrk`
- Threads: `1`
- Connections: `1`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] Routing Proxy
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:18081/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    95.44us  115.25us   3.86ms   99.42%
    Req/Sec     9.24k   742.55    10.12k    87.13%
  92812 requests in 10.10s, 12.13MB read
Requests/sec:   9189.96
Transfer/sec:      1.20MB
[Lua] backend markers: coding=39834 math=36751 others=16227 unknown=0
[Lua] expected routes: coding=34812 math=35979 others=22021 unknown=0
[Lua] aggregate route agreement: 0.937573 (87018/92812); fifo_matches=78897 fifo_mismatches=13915
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.38ms  784.32us   7.92ms   65.83%
    Req/Sec   414.74     38.41   494.00     61.00%
  4131 requests in 10.00s, 1.51MB read
Requests/sec:    413.04
Transfer/sec:    154.88KB
[Lua] backend markers: coding=1411 math=1394 others=1326 unknown=0
[Lua] expected routes: coding=1570 math=1588 others=973 unknown=0
[Lua] aggregate route agreement: 0.914549 (3778/4131); fifo_matches=3015 fifo_mismatches=1116
```
