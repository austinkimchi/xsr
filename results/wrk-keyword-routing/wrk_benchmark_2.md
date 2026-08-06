# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug  6 01:02:13 PM PDT 2026`
- Tool: `wrk`
- Threads: `2`
- Connections: `2`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   136.85us   45.72us   3.31ms   86.92%
    Req/Sec     6.35k   179.60     6.82k    75.58%
  380292 requests in 30.10s, 49.91MB read
Requests/sec:  12634.41
Transfer/sec:      1.66MB
[Lua] backend markers: coding=163222 math=150535 others=66535 unknown=0
[Lua] expected routes: coding=142628 math=147365 others=90299 unknown=0
[Lua] aggregate route agreement: 0.937511 (356528/380292); fifo_matches=323254 fifo_mismatches=57038
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://127.0.0.1:8899/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.75ms    0.88ms   7.70ms   67.07%
    Req/Sec   360.30     32.40   434.00     67.50%
  21532 requests in 30.01s, 7.88MB read
Requests/sec:    717.42
Transfer/sec:    269.00KB
[Lua] backend markers: coding=7199 math=7376 others=6957 unknown=0
[Lua] expected routes: coding=8079 math=8357 others=5096 unknown=0
[Lua] aggregate route agreement: 0.913570 (19671/21532); fifo_matches=15713 fifo_mismatches=5819
```
