# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:51:03 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `32`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.21ms  370.13us  13.63ms   96.39%
    Req/Sec     6.47k   553.49    16.53k    96.01%
  258106 requests in 10.10s, 33.73MB read
Requests/sec:  25555.63
Transfer/sec:      3.34MB
[Lua] backend markers: coding=110801 math=102177 others=45128 unknown=0
[Lua] expected routes: coding=96833 math=100028 others=61245 unknown=0
[Lua] aggregate route agreement: 0.937557 (241989/258106); fifo_matches=219404 fifo_mismatches=38702
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    34.41ms    7.46ms 117.40ms   82.02%
    Req/Sec   232.90     33.93   320.00     67.75%
  9282 requests in 10.00s, 3.41MB read
Requests/sec:    927.75
Transfer/sec:    349.01KB
[Lua] backend markers: coding=3199 math=3243 others=2840 unknown=0
[Lua] expected routes: coding=3517 math=3654 others=2111 unknown=0
[Lua] aggregate route agreement: 0.921461 (8553/9282); fifo_matches=6806 fifo_mismatches=2476
```
