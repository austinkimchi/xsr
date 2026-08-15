# High-Performance wrk Benchmark Results

- Timestamp: `Fri Aug 14 04:09:40 PM PDT 2026`
- Tool: `wrk`
- Threads: `1`
- Connections: `1`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   381.14us  182.20us   3.57ms   64.99%
    Req/Sec     2.53k    68.47     2.67k    76.74%
  75758 requests in 30.10s, 9.91MB read
Requests/sec:   2516.91
Transfer/sec:    337.17KB
[Lua] backend markers: coding=25279 math=25591 others=24888 unknown=0
[Lua] expected routes: coding=28417 math=29375 others=17966 unknown=0
[Lua] aggregate route agreement: 0.908630 (68836/75758); fifo_matches=54935 fifo_mismatches=20823
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.34ms  748.02us  10.64ms   65.97%
    Req/Sec   422.41     36.08   505.00     57.33%
  12625 requests in 30.01s, 4.63MB read
Requests/sec:    420.63
Transfer/sec:    157.85KB
[Lua] backend markers: coding=4239 math=4329 others=4057 unknown=0
[Lua] expected routes: coding=4745 math=4905 others=2975 unknown=0
[Lua] aggregate route agreement: 0.914297 (11543/12625); fifo_matches=9215 fifo_mismatches=3410
```
