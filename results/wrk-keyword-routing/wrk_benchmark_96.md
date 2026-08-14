# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 13 23:04:31 PDT 2026`
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
    Latency    30.78ms    7.04ms 100.02ms   92.26%
    Req/Sec   786.47    135.33     3.10k    92.15%
  93730 requests in 30.03s, 12.24MB read
Requests/sec:   3121.42
Transfer/sec:    417.34KB
[Lua] backend markers: coding=29816 math=28863 others=35051 unknown=0
[Lua] expected routes: coding=35232 math=36286 others=22212 unknown=0
[Lua] aggregate route agreement: 0.863021 (80891/93730); fifo_matches=68764 fifo_mismatches=24966
[Lua] warning: backend marker agreement is low; verify the target has reloaded policy config with distinct backend endpoints
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   103.88ms   20.53ms 331.73ms   89.46%
    Req/Sec   231.81     41.33   373.00     74.33%
  27718 requests in 30.03s, 10.15MB read
Requests/sec:    922.89
Transfer/sec:    345.99KB
[Lua] backend markers: coding=9279 math=9502 others=8937 unknown=0
[Lua] expected routes: coding=10403 math=10762 others=6553 unknown=0
[Lua] aggregate route agreement: 0.913991 (25334/27718); fifo_matches=20237 fifo_mismatches=7481
```
