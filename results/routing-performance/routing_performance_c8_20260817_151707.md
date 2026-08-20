# High-Performance wrk Benchmark Results

- Timestamp: `Mon Aug 17 03:17:07 PM PDT 2026`
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
    Latency    46.34us   54.27us   3.83ms   98.68%
    Req/Sec    30.41k     2.24k   35.22k    64.53%
  3633972 requests in 30.10s, 481.30MB read
Requests/sec: 120732.57
Transfer/sec:     15.99MB
[Lua] latency percentiles: p50=40.00us p95=65.00us p99=117.00us
[Lua] backend markers: coding=3633972 math=0 others=0 unknown=0
[Lua] expected routes: coding=1362791 math=1408163 others=863018 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.49ms    1.14ms  14.62ms   80.48%
    Req/Sec   791.03    121.64     1.20k    71.39%
  94677 requests in 30.10s, 12.36MB read
Requests/sec:   3145.49
Transfer/sec:    420.39KB
[Lua] latency percentiles: p50=2220.00us p95=4785.00us p99=6702.00us
[Lua] backend markers: coding=31679 math=31959 others=31039 unknown=0
[Lua] expected routes: coding=35559 math=36695 others=22423 unknown=0
[Lua] aggregate route agreement: 0.908996 (86061/94677); fifo_matches=68666 fifo_mismatches=26011
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.52ms    2.32ms  26.00ms   69.72%
    Req/Sec   234.64     32.25   330.00     58.42%
  28052 requests in 30.02s, 10.27MB read
Requests/sec:    934.57
Transfer/sec:    350.38KB
[Lua] latency percentiles: p50=8362.00us p95=12457.00us p99=14434.00us
[Lua] backend markers: coding=9492 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10609 math=10818 others=6625 unknown=0
[Lua] aggregate route agreement: 0.913625 (25629/28052); fifo_matches=20469 fifo_mismatches=7583
```
