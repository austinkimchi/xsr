# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:49:46 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `8`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   326.59us  164.93us   5.15ms   84.53%
    Req/Sec     5.54k   390.56    10.08k    90.80%
  221798 requests in 10.10s, 28.98MB read
Requests/sec:  21961.98
Transfer/sec:      2.87MB
[Lua] backend markers: coding=95239 math=87776 others=38783 unknown=0
[Lua] expected routes: coding=83237 math=85930 others=52631 unknown=0
[Lua] aggregate route agreement: 0.937565 (207950/221798); fifo_matches=188540 fifo_mismatches=33258
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.47ms    2.28ms  22.69ms   69.70%
    Req/Sec   235.98     35.65   320.00     65.50%
  9407 requests in 10.01s, 3.45MB read
Requests/sec:    939.93
Transfer/sec:    352.96KB
[Lua] backend markers: coding=3199 math=3264 others=2944 unknown=0
[Lua] expected routes: coding=3550 math=3680 others=2177 unknown=0
[Lua] aggregate route agreement: 0.918465 (8640/9407); fifo_matches=6890 fifo_mismatches=2517
```
