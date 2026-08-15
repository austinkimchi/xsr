# High-Performance wrk Benchmark Results

- Timestamp: `Fri Aug 14 10:56:04 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `64`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    18.62ms    2.08ms  33.51ms   73.29%
    Req/Sec     0.86k    61.38     1.36k    75.50%
  102855 requests in 30.08s, 13.43MB read
Requests/sec:   3419.94
Transfer/sec:    457.20KB
[Lua] backend markers: coding=34375 math=34668 others=33812 unknown=0
[Lua] expected routes: coding=38629 math=39820 others=24406 unknown=0
[Lua] aggregate route agreement: 0.908551 (93449/102855); fifo_matches=74581 fifo_mismatches=28274
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    68.13ms   13.58ms 198.03ms   84.51%
    Req/Sec   235.50     40.68   333.00     58.92%
  28161 requests in 30.03s, 10.31MB read
Requests/sec:    937.81
Transfer/sec:    351.72KB
[Lua] backend markers: coding=9591 math=9522 others=9048 unknown=0
[Lua] expected routes: coding=10678 math=10849 others=6634 unknown=0
[Lua] aggregate route agreement: 0.914279 (25747/28161); fifo_matches=20545 fifo_mismatches=7616
```
