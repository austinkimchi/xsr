# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:00:18 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `32`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] Routing Proxy
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:18081/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.23ms    1.74ms  18.34ms   87.30%
    Req/Sec     9.23k     5.06k   16.30k    65.00%
  367739 requests in 10.03s, 48.08MB read
Requests/sec:  36668.68
Transfer/sec:      4.79MB
[Lua] backend markers: coding=157845 math=145583 others=64311 unknown=0
[Lua] expected routes: coding=137947 math=142522 others=87270 unknown=0
[Lua] aggregate route agreement: 0.937567 (344780/367739); fifo_matches=312598 fifo_mismatches=55141
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    34.63ms    7.88ms  89.62ms   78.90%
    Req/Sec   231.43     37.48   340.00     65.00%
  9222 requests in 10.01s, 3.39MB read
Requests/sec:    921.66
Transfer/sec:    346.82KB
[Lua] backend markers: coding=3199 math=3211 others=2812 unknown=0
[Lua] expected routes: coding=3503 math=3623 others=2096 unknown=0
[Lua] aggregate route agreement: 0.922360 (8506/9222); fifo_matches=6762 fifo_mismatches=2460
```
