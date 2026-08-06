# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug  6 01:05:16 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `10`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   327.71us  115.88us   3.58ms   78.64%
    Req/Sec     5.42k   185.32     5.94k    79.24%
  649911 requests in 30.10s, 85.24MB read
Requests/sec:  21592.17
Transfer/sec:      2.83MB
[Lua] backend markers: coding=279003 math=257200 others=113708 unknown=0
[Lua] expected routes: coding=243812 math=251785 others=154314 unknown=0
[Lua] aggregate route agreement: 0.937521 (609305/649911); fifo_matches=552435 fifo_mismatches=97476
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.54ms    2.37ms  28.86ms   69.98%
    Req/Sec   233.92     33.99   313.00     67.42%
  27968 requests in 30.02s, 10.24MB read
Requests/sec:    931.71
Transfer/sec:    349.21KB
[Lua] backend markers: coding=9408 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10547 math=10801 others=6620 unknown=0
[Lua] aggregate route agreement: 0.913186 (25540/27968); fifo_matches=20407 fifo_mismatches=7561
```
