# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug  6 01:06:18 PM PDT 2026`
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
    Latency   595.36us  207.16us  11.70ms   90.50%
    Req/Sec     6.37k   192.33     7.30k    84.75%
  760511 requests in 30.01s, 99.82MB read
Requests/sec:  25344.87
Transfer/sec:      3.33MB
[Lua] backend markers: coding=326411 math=301058 others=133042 unknown=0
[Lua] expected routes: coding=285233 math=294722 others=180556 unknown=0
[Lua] aggregate route agreement: 0.937524 (712997/760511); fifo_matches=646451 fifo_mismatches=114060
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    17.23ms    3.97ms  57.85ms   74.90%
    Req/Sec   232.65     33.27   310.00     68.17%
  27819 requests in 30.02s, 10.18MB read
Requests/sec:    926.63
Transfer/sec:    347.23KB
[Lua] backend markers: coding=9291 math=9509 others=9019 unknown=0
[Lua] expected routes: coding=10437 math=10781 others=6601 unknown=0
[Lua] aggregate route agreement: 0.913081 (25401/27819); fifo_matches=20296 fifo_mismatches=7523
```
