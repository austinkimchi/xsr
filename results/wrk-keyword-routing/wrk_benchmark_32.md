# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug  6 01:07:19 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `32`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.21ms  193.01us  12.48ms   68.45%
    Req/Sec     6.40k   175.47     6.97k    82.23%
  766257 requests in 30.10s, 100.57MB read
Requests/sec:  25457.04
Transfer/sec:      3.34MB
[Lua] backend markers: coding=328879 math=303314 others=134064 unknown=0
[Lua] expected routes: coding=287389 math=296927 others=181941 unknown=0
[Lua] aggregate route agreement: 0.937518 (718380/766257); fifo_matches=651337 fifo_mismatches=114920
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    34.58ms    7.19ms 114.59ms   81.46%
    Req/Sec   232.10     33.14   320.00     68.17%
  27752 requests in 30.02s, 10.16MB read
Requests/sec:    924.59
Transfer/sec:    346.56KB
[Lua] backend markers: coding=9279 math=9506 others=8967 unknown=0
[Lua] expected routes: coding=10414 math=10770 others=6568 unknown=0
[Lua] aggregate route agreement: 0.913556 (25353/27752); fifo_matches=20252 fifo_mismatches=7500
```
