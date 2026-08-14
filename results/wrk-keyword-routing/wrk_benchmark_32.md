# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 13 23:02:29 PDT 2026`
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
    Latency     9.73ms    1.90ms  33.13ms   66.23%
    Req/Sec   821.77     78.63     0.99k    59.00%
  98197 requests in 30.01s, 12.82MB read
Requests/sec:   3271.82
Transfer/sec:    437.52KB
[Lua] backend markers: coding=31259 math=30208 others=36730 unknown=0
[Lua] expected routes: coding=36924 math=37998 others=23275 unknown=0
[Lua] aggregate route agreement: 0.862980 (84742/98197); fifo_matches=72035 fifo_mismatches=26162
[Lua] warning: backend marker agreement is low; verify the target has reloaded policy config with distinct backend endpoints
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    34.21ms    7.04ms  90.95ms   78.47%
    Req/Sec   234.53     34.05   323.00     58.50%
  28044 requests in 30.02s, 10.27MB read
Requests/sec:    934.12
Transfer/sec:    350.20KB
[Lua] backend markers: coding=9484 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10603 math=10814 others=6627 unknown=0
[Lua] aggregate route agreement: 0.913671 (25623/28044); fifo_matches=20463 fifo_mismatches=7581
```
