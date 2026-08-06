# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:50:13 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `10`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   331.04us  147.89us   4.77ms   82.11%
    Req/Sec     5.43k   255.48     6.16k    72.28%
  218066 requests in 10.10s, 28.49MB read
Requests/sec:  21591.17
Transfer/sec:      2.82MB
[Lua] backend markers: coding=93659 math=86289 others=38118 unknown=0
[Lua] expected routes: coding=81867 math=84474 others=51725 unknown=0
[Lua] aggregate route agreement: 0.937601 (204459/218066); fifo_matches=185373 fifo_mismatches=32693
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.55ms    2.47ms  23.38ms   69.65%
    Req/Sec   233.52     35.94   313.00     65.25%
  9308 requests in 10.01s, 3.42MB read
Requests/sec:    929.78
Transfer/sec:    349.76KB
[Lua] backend markers: coding=3199 math=3260 others=2849 unknown=0
[Lua] expected routes: coding=3524 math=3672 others=2112 unknown=0
[Lua] aggregate route agreement: 0.920821 (8571/9308); fifo_matches=6823 fifo_mismatches=2485
```
