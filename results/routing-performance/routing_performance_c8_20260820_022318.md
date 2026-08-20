# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 20 02:23:18 AM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `8`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/3] Direct Backend
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18391/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    47.30us   55.29us   4.41ms   98.67%
    Req/Sec    29.82k     2.10k   34.12k    64.87%
  3572547 requests in 30.10s, 473.16MB read
Requests/sec: 118689.70
Transfer/sec:     15.72MB
[Lua] latency percentiles: p50=41.00us p95=67.00us p99=119.00us
[Lua] backend markers: coding=3572547 math=0 others=0 unknown=0
[Lua] expected routes: coding=1339739 math=1384370 others=848438 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.49ms    1.12ms  14.11ms   79.87%
    Req/Sec   790.25    116.60     2.09k    71.01%
  94487 requests in 30.09s, 12.33MB read
Requests/sec:   3139.90
Transfer/sec:    419.62KB
[Lua] latency percentiles: p50=2221.00us p95=4762.00us p99=6560.00us
[Lua] backend markers: coding=31607 math=32226 others=30654 unknown=0
[Lua] expected routes: coding=35503 math=36573 others=22411 unknown=0
[Lua] aggregate route agreement: 0.912760 (86244/94487); fifo_matches=68908 fifo_mismatches=25579
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.59ms    2.13ms  25.07ms   70.88%
    Req/Sec   232.74     25.13   310.00     70.17%
  27826 requests in 30.02s, 10.19MB read
Requests/sec:    926.98
Transfer/sec:    347.74KB
[Lua] latency percentiles: p50=8515.00us p95=12132.00us p99=14078.00us
[Lua] backend markers: coding=9417 math=9501 others=8908 unknown=0
[Lua] expected routes: coding=10508 math=10783 others=6535 unknown=0
[Lua] aggregate route agreement: 0.914720 (25453/27826); fifo_matches=20314 fifo_mismatches=7512
```
