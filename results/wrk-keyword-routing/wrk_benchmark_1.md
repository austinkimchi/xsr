# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:42:31 PM PDT 2026`
- Tool: `wrk`
- Threads: `1`
- Connections: `1`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   125.47us  130.50us   3.70ms   99.38%
    Req/Sec     7.32k   273.47     7.84k    66.00%
  72914 requests in 10.00s, 9.53MB read
Requests/sec:   7290.39
Transfer/sec:      0.95MB
[Lua] backend markers: coding=31295 math=28869 others=12750 unknown=0
[Lua] expected routes: coding=27348 math=28263 others=17303 unknown=0
[Lua] aggregate route agreement: 0.937557 (68361/72914); fifo_matches=61983 fifo_mismatches=10931
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.40ms  792.66us   6.84ms   66.85%
    Req/Sec   413.03     37.42   505.00     64.00%
  4115 requests in 10.00s, 1.51MB read
Requests/sec:    411.35
Transfer/sec:    154.19KB
[Lua] backend markers: coding=1395 math=1394 others=1326 unknown=0
[Lua] expected routes: coding=1559 math=1584 others=972 unknown=0
[Lua] aggregate route agreement: 0.913973 (3761/4115); fifo_matches=3004 fifo_mismatches=1111
```
