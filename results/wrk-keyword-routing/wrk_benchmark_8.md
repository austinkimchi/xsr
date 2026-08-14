# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 13 22:59:24 PDT 2026`
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
    Latency     2.69ms    1.72ms  43.28ms   88.25%
    Req/Sec   757.13    156.09     1.34k    76.00%
  90512 requests in 30.09s, 11.82MB read
Requests/sec:   3008.35
Transfer/sec:    402.17KB
[Lua] backend markers: coding=28735 math=27921 others=33856 unknown=0
[Lua] expected routes: coding=33978 math=35081 others=21453 unknown=0
[Lua] aggregate route agreement: 0.862968 (78109/90512); fifo_matches=66395 fifo_mismatches=24117
[Lua] warning: backend marker agreement is low; verify the target has reloaded policy config with distinct backend endpoints
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.54ms    2.35ms  25.06ms   69.61%
    Req/Sec   233.87     34.66   330.00     65.67%
  27964 requests in 30.02s, 10.24MB read
Requests/sec:    931.60
Transfer/sec:    349.16KB
[Lua] backend markers: coding=9404 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10545 math=10799 others=6620 unknown=0
[Lua] aggregate route agreement: 0.913174 (25536/27964); fifo_matches=20405 fifo_mismatches=7559
```
