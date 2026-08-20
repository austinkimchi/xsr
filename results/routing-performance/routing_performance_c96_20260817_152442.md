# High-Performance wrk Benchmark Results

- Timestamp: `Mon Aug 17 03:24:42 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `96`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/3] Direct Backend
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18391/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   409.55us  191.54us   7.34ms   85.73%
    Req/Sec    30.01k     2.43k   35.59k    65.42%
  3583580 requests in 30.01s, 474.62MB read
Requests/sec: 119425.28
Transfer/sec:     15.82MB
[Lua] latency percentiles: p50=371.00us p95=753.00us p99=1132.00us
[Lua] backend markers: coding=3583580 math=0 others=0 unknown=0
[Lua] expected routes: coding=1343860 math=1388654 others=851066 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    30.05ms    2.88ms  39.68ms   67.72%
    Req/Sec   800.37     57.44     1.15k    59.42%
  95636 requests in 30.05s, 12.48MB read
Requests/sec:   3182.66
Transfer/sec:    425.37KB
[Lua] latency percentiles: p50=29737.00us p95=34943.00us p99=36379.00us
[Lua] backend markers: coding=31999 math=32321 others=31316 unknown=0
[Lua] expected routes: coding=35914 math=37092 others=22630 unknown=0
[Lua] aggregate route agreement: 0.909176 (86950/95636); fifo_matches=69371 fifo_mismatches=26265
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   102.87ms   20.12ms 351.94ms   86.62%
    Req/Sec   233.96     37.26   343.00     69.33%
  27970 requests in 30.02s, 10.24MB read
Requests/sec:    931.69
Transfer/sec:    349.21KB
[Lua] latency percentiles: p50=98247.00us p95=126285.00us p99=167489.00us
[Lua] backend markers: coding=9410 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10548 math=10800 others=6622 unknown=0
[Lua] aggregate route agreement: 0.913264 (25544/27970); fifo_matches=20408 fifo_mismatches=7562
```
