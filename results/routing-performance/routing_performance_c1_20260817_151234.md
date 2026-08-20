# High-Performance wrk Benchmark Results

- Timestamp: `Mon Aug 17 03:12:34 PM PDT 2026`
- Tool: `wrk`
- Threads: `1`
- Connections: `1`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/3] Direct Backend
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18391/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    20.97us   13.48us   1.86ms   97.85%
    Req/Sec    27.14k     1.79k   30.29k    73.67%
  810129 requests in 30.00s, 107.29MB read
Requests/sec:  27003.71
Transfer/sec:      3.58MB
[Lua] latency percentiles: p50=20.00us p95=28.00us p99=42.00us
[Lua] backend markers: coding=810129 math=0 others=0 unknown=0
[Lua] expected routes: coding=303814 math=313930 others=192385 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   386.52us  184.33us   3.38ms   65.07%
    Req/Sec     2.50k    67.05     2.62k    75.75%
  74755 requests in 30.10s, 9.78MB read
Requests/sec:   2483.54
Transfer/sec:    332.70KB
[Lua] latency percentiles: p50=361.00us p95=714.00us p99=875.00us
[Lua] backend markers: coding=24959 math=25227 others=24569 unknown=0
[Lua] expected routes: coding=28053 math=28966 others=17736 unknown=0
[Lua] aggregate route agreement: 0.908595 (67922/74755); fifo_matches=54203 fifo_mismatches=20552
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.33ms  738.80us   5.83ms   65.28%
    Req/Sec   424.22     33.53   520.00     59.67%
  12677 requests in 30.02s, 4.64MB read
Requests/sec:    422.31
Transfer/sec:    158.41KB
[Lua] latency percentiles: p50=2224.00us p95=3693.00us p99=4226.00us
[Lua] backend markers: coding=4239 math=4342 others=4096 unknown=0
[Lua] expected routes: coding=4758 math=4920 others=2999 unknown=0
[Lua] aggregate route agreement: 0.913465 (11580/12677); fifo_matches=9251 fifo_mismatches=3426
```
