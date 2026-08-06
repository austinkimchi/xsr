# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 10:58:24 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `4`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] Routing Proxy
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:18081/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   108.46us  101.42us   4.58ms   99.53%
    Req/Sec     7.57k   428.46     8.56k    77.97%
  304376 requests in 10.10s, 39.79MB read
Requests/sec:  30136.94
Transfer/sec:      3.94MB
[Lua] backend markers: coding=130682 math=120462 others=53232 unknown=0
[Lua] expected routes: coding=114210 math=117926 others=72240 unknown=0
[Lua] aggregate route agreement: 0.937551 (285368/304376); fifo_matches=258733 fifo_mismatches=45643
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.43ms    1.52ms  15.34ms   68.07%
    Req/Sec   224.55     33.75   292.00     65.25%
  8948 requests in 10.01s, 3.28MB read
Requests/sec:    894.30
Transfer/sec:    335.82KB
[Lua] backend markers: coding=3188 math=2952 others=2808 unknown=0
[Lua] expected routes: coding=3476 math=3400 others=2072 unknown=0
[Lua] aggregate route agreement: 0.917747 (8212/8948); fifo_matches=6536 fifo_mismatches=2412
```
