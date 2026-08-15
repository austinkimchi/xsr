# High-Performance wrk Benchmark Results

- Timestamp: `Fri Aug 14 04:10:46 PM PDT 2026`
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
    Latency   738.02us  329.06us   4.00ms   70.75%
    Req/Sec     1.32k    89.29     1.59k    65.17%
  79086 requests in 30.01s, 10.34MB read
Requests/sec:   2635.39
Transfer/sec:    352.70KB
[Lua] backend markers: coding=26399 math=26720 others=25967 unknown=0
[Lua] expected routes: coding=29667 math=30666 others=18753 unknown=0
[Lua] aggregate route agreement: 0.908783 (71872/79086); fifo_matches=57356 fifo_mismatches=21730
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.74ms    0.88ms   7.92ms   66.56%
    Req/Sec   361.94     32.68   434.00     67.67%
  21631 requests in 30.02s, 7.92MB read
Requests/sec:    720.52
Transfer/sec:    270.07KB
[Lua] backend markers: coding=7231 math=7380 others=7020 unknown=0
[Lua] expected routes: coding=8128 math=8371 others=5132 unknown=0
[Lua] aggregate route agreement: 0.912718 (19743/21631); fifo_matches=15778 fifo_mismatches=5853
```
