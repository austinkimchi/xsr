# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 20 02:24:48 AM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `10`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/3] Direct Backend
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18391/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    46.94us   47.24us   3.32ms   98.49%
    Req/Sec    29.43k     2.52k   33.99k    67.86%
  3526012 requests in 30.10s, 466.99MB read
Requests/sec: 117145.08
Transfer/sec:     15.51MB
[Lua] latency percentiles: p50=42.00us p95=67.00us p99=112.00us
[Lua] backend markers: coding=3526012 math=0 others=0 unknown=0
[Lua] expected routes: coding=1322295 math=1366338 others=837379 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.47ms    1.11ms  16.83ms   80.25%
    Req/Sec   791.05    122.81     2.44k    74.60%
  94557 requests in 30.09s, 12.34MB read
Requests/sec:   3142.11
Transfer/sec:    419.92KB
[Lua] latency percentiles: p50=2204.00us p95=4721.00us p99=6568.00us
[Lua] backend markers: coding=31669 math=32234 others=30654 unknown=0
[Lua] expected routes: coding=35546 math=36595 others=22416 unknown=0
[Lua] aggregate route agreement: 0.912878 (86319/94557); fifo_matches=68958 fifo_mismatches=25599
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.57ms    2.28ms  27.11ms   69.87%
    Req/Sec   233.12     32.47   333.00     65.33%
  27868 requests in 30.02s, 10.20MB read
Requests/sec:    928.35
Transfer/sec:    347.91KB
[Lua] latency percentiles: p50=8450.00us p95=12397.00us p99=14355.00us
[Lua] backend markers: coding=9331 math=9510 others=9027 unknown=0
[Lua] expected routes: coding=10474 math=10787 others=6607 unknown=0
[Lua] aggregate route agreement: 0.913162 (25448/27868); fifo_matches=20333 fifo_mismatches=7535
```
