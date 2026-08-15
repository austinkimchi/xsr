# High-Performance wrk Benchmark Results

- Timestamp: `Fri Aug 14 04:55:18 PM PDT 2026`
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
    Latency     9.17ms    1.62ms  47.66ms   65.03%
    Req/Sec     0.87k    75.30     1.07k    59.58%
  104090 requests in 30.02s, 13.59MB read
Requests/sec:   3467.61
Transfer/sec:    463.58KB
[Lua] backend markers: coding=34821 math=35140 others=34129 unknown=0
[Lua] expected routes: coding=39094 math=40341 others=24655 unknown=0
[Lua] aggregate route agreement: 0.908983 (94616/104090); fifo_matches=75492 fifo_mismatches=28598
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    33.94ms    7.37ms  93.90ms   79.27%
    Req/Sec   236.42     35.53   320.00     63.33%
  28270 requests in 30.02s, 10.36MB read
Requests/sec:    941.76
Transfer/sec:    353.30KB
[Lua] backend markers: coding=9599 math=9623 others=9048 unknown=0
[Lua] expected routes: coding=10693 math=10932 others=6645 unknown=0
[Lua] aggregate route agreement: 0.914998 (25867/28270); fifo_matches=20631 fifo_mismatches=7639
```
