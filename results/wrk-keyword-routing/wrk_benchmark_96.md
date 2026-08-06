# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug  6 01:09:21 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `96`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.39ms  832.33us   8.84ms   63.86%
    Req/Sec     5.44k     0.89k   16.44k    64.36%
  649605 requests in 30.10s, 85.20MB read
Requests/sec:  21582.43
Transfer/sec:      2.83MB
[Lua] backend markers: coding=278803 math=257186 others=113616 unknown=0
[Lua] expected routes: coding=243640 math=251777 others=154188 unknown=0
[Lua] aggregate route agreement: 0.937544 (609033/649605); fifo_matches=552190 fifo_mismatches=97415
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   103.02ms   20.00ms 307.54ms   89.00%
    Req/Sec   233.52     37.96   390.00     71.75%
  27921 requests in 30.03s, 10.22MB read
Requests/sec:    929.65
Transfer/sec:    348.38KB
[Lua] backend markers: coding=9361 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10510 math=10793 others=6618 unknown=0
[Lua] aggregate route agreement: 0.912969 (25491/27921); fifo_matches=20370 fifo_mismatches=7551
```
