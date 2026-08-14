# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 13 23:03:30 PDT 2026`
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
    Latency    18.80ms    2.09ms  26.47ms   70.65%
    Req/Sec     0.85k    55.98     1.16k    61.55%
  101770 requests in 30.03s, 13.29MB read
Requests/sec:   3388.82
Transfer/sec:    453.21KB
[Lua] backend markers: coding=32318 math=31371 others=38081 unknown=0
[Lua] expected routes: coding=38217 math=39423 others=24130 unknown=0
[Lua] aggregate route agreement: 0.862916 (87819/101770); fifo_matches=74656 fifo_mismatches=27114
[Lua] warning: backend marker agreement is low; verify the target has reloaded policy config with distinct backend endpoints
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    68.55ms   13.11ms 230.53ms   86.23%
    Req/Sec   234.09     40.21   333.00     63.67%
  27991 requests in 30.03s, 10.25MB read
Requests/sec:    932.11
Transfer/sec:    349.39KB
[Lua] backend markers: coding=9432 math=9511 others=9048 unknown=0
[Lua] expected routes: coding=10561 math=10808 others=6622 unknown=0
[Lua] aggregate route agreement: 0.913329 (25565/27991); fifo_matches=20420 fifo_mismatches=7571
```
