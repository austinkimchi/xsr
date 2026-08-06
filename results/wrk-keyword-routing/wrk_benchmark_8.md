# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug  6 01:04:15 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `8`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   327.24us  115.26us   3.65ms   78.61%
    Req/Sec     5.44k   193.40     7.13k    83.71%
  651430 requests in 30.10s, 85.44MB read
Requests/sec:  21642.27
Transfer/sec:      2.84MB
[Lua] backend markers: coding=279585 math=257885 others=113960 unknown=0
[Lua] expected routes: coding=244311 math=252461 others=154658 unknown=0
[Lua] aggregate route agreement: 0.937525 (610732/651430); fifo_matches=553735 fifo_mismatches=97695
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.54ms    2.21ms  24.39ms   69.07%
    Req/Sec   234.11     30.79   313.00     60.42%
  27990 requests in 30.02s, 10.25MB read
Requests/sec:    932.49
Transfer/sec:    349.53KB
[Lua] backend markers: coding=9430 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10561 math=10806 others=6623 unknown=0
[Lua] aggregate route agreement: 0.913362 (25565/27990); fifo_matches=20421 fifo_mismatches=7569
```
