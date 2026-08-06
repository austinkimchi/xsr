# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 10:59:55 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `16`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] Routing Proxy
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:18081/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   688.51us    0.96ms  11.65ms   85.73%
    Req/Sec     9.00k     4.82k   15.20k    64.25%
  358581 requests in 10.01s, 46.88MB read
Requests/sec:  35811.81
Transfer/sec:      4.68MB
[Lua] backend markers: coding=153926 math=141924 others=62731 unknown=0
[Lua] expected routes: coding=134510 math=138939 others=85132 unknown=0
[Lua] aggregate route agreement: 0.937529 (336180/358581); fifo_matches=304808 fifo_mismatches=53773
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    17.44ms    4.46ms  48.60ms   74.73%
    Req/Sec   229.62     35.10   292.00     64.50%
  9153 requests in 10.01s, 3.36MB read
Requests/sec:    914.73
Transfer/sec:    344.06KB
[Lua] backend markers: coding=3199 math=3146 others=2808 unknown=0
[Lua] expected routes: coding=3497 math=3564 others=2092 unknown=0
[Lua] aggregate route agreement: 0.921774 (8437/9153); fifo_matches=6703 fifo_mismatches=2450
```
