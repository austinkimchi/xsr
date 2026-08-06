# High-Performance wrk Benchmark Results

- Timestamp: `Wed Aug  5 10:59:26 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `10`
- Duration: `10s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/2] Routing Proxy
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:18081/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   335.25us  600.18us  10.10ms   90.38%
    Req/Sec     8.97k     3.59k   12.99k    68.73%
  359670 requests in 10.10s, 47.02MB read
Requests/sec:  35614.42
Transfer/sec:      4.66MB
[Lua] backend markers: coding=154413 math=142328 others=62929 unknown=0
[Lua] expected routes: coding=134942 math=139331 others=85397 unknown=0
[Lua] aggregate route agreement: 0.937532 (337202/359670); fifo_matches=305725 fifo_mismatches=53945
```

## [2/2] vLLM-SR Route
```
[Lua] Loaded 240 prompts from benchmarks/dataset_prompts.jsonl
Running 10s test @ http://127.0.0.1:8899/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.51ms    2.29ms  21.29ms   69.30%
    Req/Sec   234.58     35.33   313.00     66.75%
  9351 requests in 10.01s, 3.43MB read
Requests/sec:    934.18
Transfer/sec:    351.13KB
[Lua] backend markers: coding=3199 math=3260 others=2892 unknown=0
[Lua] expected routes: coding=3537 math=3672 others=2142 unknown=0
[Lua] aggregate route agreement: 0.919795 (8601/9351); fifo_matches=6853 fifo_mismatches=2498
```
