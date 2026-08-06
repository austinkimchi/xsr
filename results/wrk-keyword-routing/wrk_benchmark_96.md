# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:02:13 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `96`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] Routing Proxy
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:18081/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.95ms    4.51ms  51.11ms   88.53%
    Req/Sec     9.69k     5.20k   27.96k    64.48%
  384409 requests in 10.09s, 50.26MB read
Requests/sec:  38103.21
Transfer/sec:      4.98MB
[Lua] backend markers: coding=165019 math=152168 others=67222 unknown=0
[Lua] expected routes: coding=144215 math=148964 others=91230 unknown=0
[Lua] aggregate route agreement: 0.937546 (360401/384409); fifo_matches=326766 fifo_mismatches=57643
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   104.85ms   21.94ms 269.46ms   83.91%
    Req/Sec   228.79     40.54   333.00     68.75%
  9120 requests in 10.02s, 3.35MB read
Requests/sec:    910.18
Transfer/sec:    342.26KB
[Lua] backend markers: coding=3199 math=3113 others=2808 unknown=0
[Lua] expected routes: coding=3496 math=3535 others=2089 unknown=0
[Lua] aggregate route agreement: 0.921162 (8401/9120); fifo_matches=6674 fifo_mismatches=2446
```
