# High-Performance wrk Benchmark Results

- Timestamp: `Fri Aug 14 04:14:30 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `10`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.38ms    1.08ms  15.09ms   80.34%
    Req/Sec   820.33    118.04     1.22k    68.89%
  98174 requests in 30.10s, 12.81MB read
Requests/sec:   3261.86
Transfer/sec:    435.99KB
[Lua] backend markers: coding=32799 math=33166 others=32209 unknown=0
[Lua] expected routes: coding=36843 math=38064 others=23267 unknown=0
[Lua] aggregate route agreement: 0.908917 (89232/98174); fifo_matches=71205 fifo_mismatches=26969
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.47ms    2.29ms  23.75ms   69.77%
    Req/Sec   235.88     32.75   323.00     55.42%
  28200 requests in 30.02s, 10.33MB read
Requests/sec:    939.49
Transfer/sec:    352.38KB
[Lua] backend markers: coding=9584 math=9568 others=9048 unknown=0
[Lua] expected routes: coding=10678 math=10886 others=6636 unknown=0
[Lua] aggregate route agreement: 0.914468 (25788/28200); fifo_matches=20579 fifo_mismatches=7621
```
