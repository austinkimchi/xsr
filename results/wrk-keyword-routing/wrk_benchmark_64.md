# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:51:28 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `64`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.50ms  516.84us  14.97ms   92.09%
    Req/Sec     6.34k   520.93    12.59k    93.78%
  253790 requests in 10.10s, 33.17MB read
Requests/sec:  25129.42
Transfer/sec:      3.28MB
[Lua] backend markers: coding=108939 math=100470 others=44381 unknown=0
[Lua] expected routes: coding=95205 math=98357 others=60228 unknown=0
[Lua] aggregate route agreement: 0.937559 (237943/253790); fifo_matches=215739 fifo_mismatches=38051
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    69.65ms   15.15ms 223.14ms   83.09%
    Req/Sec   229.90     44.58   333.00     63.00%
  9163 requests in 10.01s, 3.37MB read
Requests/sec:    914.97
Transfer/sec:    344.17KB
[Lua] backend markers: coding=3199 math=3155 others=2809 unknown=0
[Lua] expected routes: coding=3498 math=3573 others=2092 unknown=0
[Lua] aggregate route agreement: 0.921751 (8446/9163); fifo_matches=6712 fifo_mismatches=2451
```
