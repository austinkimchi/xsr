# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 10:57:51 PM PDT 2026`
- Tool: `wrk`
- Threads: `2`
- Connections: `2`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] Routing Proxy
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:18081/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    93.58us   83.15us   3.49ms   99.42%
    Req/Sec     9.01k   678.56    10.06k    87.62%
  181111 requests in 10.10s, 23.68MB read
Requests/sec:  17932.79
Transfer/sec:      2.34MB
[Lua] backend markers: coding=77742 math=71692 others=31677 unknown=0
[Lua] expected routes: coding=67938 math=70183 others=42990 unknown=0
[Lua] aggregate route agreement: 0.937536 (169798/181111); fifo_matches=153952 fifo_mismatches=27159
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.81ms    0.94ms  13.55ms   69.89%
    Req/Sec   353.07     31.02   430.00     66.00%
  7036 requests in 10.01s, 2.58MB read
Requests/sec:    703.20
Transfer/sec:    264.26KB
[Lua] backend markers: coding=2399 math=2444 others=2193 unknown=0
[Lua] expected routes: coding=2656 math=2759 others=1621 unknown=0
[Lua] aggregate route agreement: 0.918704 (6464/7036); fifo_matches=5150 fifo_mismatches=1886
```
