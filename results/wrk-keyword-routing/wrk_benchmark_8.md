# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 10:59:03 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `8`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] Routing Proxy
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:18081/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   390.88us  673.61us   9.16ms   88.53%
    Req/Sec     8.80k     3.68k   13.09k    76.24%
  353704 requests in 10.10s, 46.24MB read
Requests/sec:  35020.36
Transfer/sec:      4.58MB
[Lua] backend markers: coding=151869 math=139959 others=61876 unknown=0
[Lua] expected routes: coding=132718 math=137013 others=83973 unknown=0
[Lua] aggregate route agreement: 0.937527 (331607/353704); fifo_matches=300658 fifo_mismatches=53046
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.54ms    2.43ms  24.73ms   70.02%
    Req/Sec   233.85     34.68   323.00     67.50%
  9322 requests in 10.01s, 3.42MB read
Requests/sec:    931.50
Transfer/sec:    350.29KB
[Lua] backend markers: coding=3199 math=3257 others=2866 unknown=0
[Lua] expected routes: coding=3529 math=3669 others=2124 unknown=0
[Lua] aggregate route agreement: 0.920403 (8580/9322); fifo_matches=6832 fifo_mismatches=2490
```
