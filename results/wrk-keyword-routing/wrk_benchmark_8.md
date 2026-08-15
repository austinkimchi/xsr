# High-Performance wrk Benchmark Results

- Timestamp: `Fri Aug 14 03:44:12 PM PDT 2026`
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
    Latency     2.36ms    1.08ms  18.22ms   80.36%
    Req/Sec   832.85    117.62     1.16k    70.48%
  99680 requests in 30.09s, 13.01MB read
Requests/sec:   3312.24
Transfer/sec:    442.75KB
[Lua] backend markers: coding=33336 math=33637 others=32707 unknown=0
[Lua] expected routes: coding=37437 math=38621 others=23622 unknown=0
[Lua] aggregate route agreement: 0.908858 (90595/99680); fifo_matches=72289 fifo_mismatches=27391
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.41ms    2.24ms  21.42ms   69.34%
    Req/Sec   237.52     33.59   333.00     57.92%
  28397 requests in 30.01s, 10.41MB read
Requests/sec:    946.10
Transfer/sec:    355.04KB
[Lua] backend markers: coding=9599 math=9748 others=9050 unknown=0
[Lua] expected routes: coding=10701 math=11041 others=6655 unknown=0
[Lua] aggregate route agreement: 0.915660 (26002/28397); fifo_matches=20740 fifo_mismatches=7657
```
