# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:49:21 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `4`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   200.71us   97.62us   3.97ms   95.35%
    Req/Sec     4.47k   141.75     4.85k    71.04%
  179609 requests in 10.10s, 23.46MB read
Requests/sec:  17783.60
Transfer/sec:      2.32MB
[Lua] backend markers: coding=77117 math=71070 others=31422 unknown=0
[Lua] expected routes: coding=67395 math=69574 others=42640 unknown=0
[Lua] aggregate route agreement: 0.937542 (168391/179609); fifo_matches=152675 fifo_mismatches=26934
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.35ms    1.44ms  12.23ms   67.20%
    Req/Sec   228.65     31.07   313.00     63.50%
  9113 requests in 10.01s, 3.35MB read
Requests/sec:    910.55
Transfer/sec:    342.38KB
[Lua] backend markers: coding=3199 math=3106 others=2808 unknown=0
[Lua] expected routes: coding=3495 math=3530 others=2088 unknown=0
[Lua] aggregate route agreement: 0.920992 (8393/9113); fifo_matches=6669 fifo_mismatches=2444
```
