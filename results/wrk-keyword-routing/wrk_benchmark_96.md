# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:51:53 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `96`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     3.76ms  490.24us   9.95ms   81.88%
    Req/Sec     6.34k   730.41    19.07k    94.76%
  252889 requests in 10.10s, 33.05MB read
Requests/sec:  25040.14
Transfer/sec:      3.27MB
[Lua] backend markers: coding=108605 math=100067 others=44217 unknown=0
[Lua] expected routes: coding=94925 math=97961 others=60003 unknown=0
[Lua] aggregate route agreement: 0.937577 (237103/252889); fifo_matches=214972 fifo_mismatches=37917
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   103.89ms   21.09ms 250.65ms   87.93%
    Req/Sec   230.79     39.99   363.00     72.00%
  9199 requests in 10.03s, 3.38MB read
Requests/sec:    917.54
Transfer/sec:    345.20KB
[Lua] backend markers: coding=3199 math=3187 others=2813 unknown=0
[Lua] expected routes: coding=3503 math=3602 others=2094 unknown=0
[Lua] aggregate route agreement: 0.921839 (8480/9199); fifo_matches=6740 fifo_mismatches=2459
```
