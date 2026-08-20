# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 20 02:30:49 AM PDT 2026`
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
    Latency   414.70us  209.94us   7.79ms   83.83%
    Req/Sec    29.69k     2.32k   35.79k    66.50%
  3545058 requests in 30.01s, 469.51MB read
Requests/sec: 118146.36
Transfer/sec:     15.65MB
[Lua] latency percentiles: p50=379.00us p95=764.00us p99=1208.00us
[Lua] backend markers: coding=3545058 math=0 others=0 unknown=0
[Lua] expected routes: coding=1329424 math=1373733 others=841901 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    30.19ms    3.14ms  48.20ms   65.80%
    Req/Sec   796.73     63.29     1.12k    63.00%
  95210 requests in 30.05s, 12.43MB read
Requests/sec:   3168.49
Transfer/sec:    423.45KB
[Lua] latency percentiles: p50=29976.00us p95=34942.00us p99=36909.00us
[Lua] backend markers: coding=31850 math=32472 others=30888 unknown=0
[Lua] expected routes: coding=35772 math=36853 others=22585 unknown=0
[Lua] aggregate route agreement: 0.912793 (86907/95210); fifo_matches=69432 fifo_mismatches=25778
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   103.50ms   21.48ms 356.77ms   88.27%
    Req/Sec   232.61     37.93   393.00     70.08%
  27812 requests in 30.02s, 10.18MB read
Requests/sec:    926.44
Transfer/sec:    347.17KB
[Lua] latency percentiles: p50=99369.00us p95=128120.00us p99=180893.00us
[Lua] backend markers: coding=9289 math=9509 others=9014 unknown=0
[Lua] expected routes: coding=10434 math=10780 others=6598 unknown=0
[Lua] aggregate route agreement: 0.913131 (25396/27812); fifo_matches=20291 fifo_mismatches=7521
```
