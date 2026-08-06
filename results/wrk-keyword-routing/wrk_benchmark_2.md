# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 11:42:57 PM PDT 2026`
- Tool: `wrk`
- Threads: `2`
- Connections: `2`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] XDP Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://10.10.0.1:18081/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   138.63us   74.50us   3.34ms   96.55%
    Req/Sec     6.37k   190.86     6.77k    67.33%
  128060 requests in 10.10s, 16.74MB read
Requests/sec:  12679.96
Transfer/sec:      1.66MB
[Lua] backend markers: coding=54961 math=50705 others=22394 unknown=0
[Lua] expected routes: coding=48032 math=49638 others=30390 unknown=0
[Lua] aggregate route agreement: 0.937561 (120064/128060); fifo_matches=108857 fifo_mismatches=19203
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.74ms    0.88ms   7.54ms   67.82%
    Req/Sec   361.45     31.55   440.00     69.50%
  7202 requests in 10.00s, 2.63MB read
Requests/sec:    719.87
Transfer/sec:    269.60KB
[Lua] backend markers: coding=2402 math=2460 others=2340 unknown=0
[Lua] expected routes: coding=2702 math=2790 others=1710 unknown=0
[Lua] aggregate route agreement: 0.912524 (6572/7202); fifo_matches=5252 fifo_mismatches=1950
```
