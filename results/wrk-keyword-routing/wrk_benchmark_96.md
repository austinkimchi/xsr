# High-Performance wrk Benchmark Results

- Timestamp: `Fri Aug 14 11:03:11 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `96`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    27.78ms    4.14ms  42.97ms   62.13%
    Req/Sec     0.87k    99.46     1.90k    61.19%
  103264 requests in 30.03s, 13.48MB read
Requests/sec:   3438.79
Transfer/sec:    459.72KB
[Lua] backend markers: coding=34474 math=34830 others=33960 unknown=0
[Lua] expected routes: coding=38760 math=39993 others=24511 unknown=0
[Lua] aggregate route agreement: 0.908497 (93815/103264); fifo_matches=74880 fifo_mismatches=28384
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   102.15ms   20.42ms 287.49ms   87.50%
    Req/Sec   235.62     39.49   393.00     74.08%
  28172 requests in 30.03s, 10.32MB read
Requests/sec:    938.14
Transfer/sec:    351.85KB
[Lua] backend markers: coding=9579 math=9545 others=9048 unknown=0
[Lua] expected routes: coding=10672 math=10866 others=6634 unknown=0
[Lua] aggregate route agreement: 0.914312 (25758/28172); fifo_matches=20556 fifo_mismatches=7616
```
