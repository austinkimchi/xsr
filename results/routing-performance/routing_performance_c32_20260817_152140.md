# High-Performance wrk Benchmark Results

- Timestamp: `Mon Aug 17 03:21:40 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `32`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/3] Direct Backend
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18391/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   142.42us   96.01us   7.30ms   90.68%
    Req/Sec    30.52k     2.20k   35.96k    66.97%
  3648878 requests in 30.10s, 483.27MB read
Requests/sec: 121226.65
Transfer/sec:     16.06MB
[Lua] latency percentiles: p50=119.00us p95=263.00us p99=458.00us
[Lua] backend markers: coding=3648878 math=0 others=0 unknown=0
[Lua] expected routes: coding=1368368 math=1413973 others=866537 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    10.05ms    1.88ms  36.48ms   65.28%
    Req/Sec   795.35     71.66     0.94k    61.50%
  95042 requests in 30.02s, 12.40MB read
Requests/sec:   3166.40
Transfer/sec:    423.19KB
[Lua] latency percentiles: p50=9848.00us p95=13307.00us p99=14907.00us
[Lua] backend markers: coding=31738 math=32072 others=31232 unknown=0
[Lua] expected routes: coding=35674 math=36822 others=22546 unknown=0
[Lua] aggregate route agreement: 0.908609 (86356/95042); fifo_matches=68921 fifo_mismatches=26121
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    34.26ms    7.22ms 106.98ms   79.19%
    Req/Sec   234.19     33.88   330.00     61.67%
  28005 requests in 30.02s, 10.25MB read
Requests/sec:    932.86
Transfer/sec:    349.68KB
[Lua] latency percentiles: p50=33032.00us p95=45169.00us p99=53518.00us
[Lua] backend markers: coding=9445 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10574 math=10807 others=6624 unknown=0
[Lua] aggregate route agreement: 0.913444 (25581/28005); fifo_matches=20434 fifo_mismatches=7571
```
