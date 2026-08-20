# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 20 02:29:19 AM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `64`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/3] Direct Backend
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18391/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   279.10us  147.17us   6.96ms   86.55%
    Req/Sec    29.75k     2.12k   35.69k    68.47%
  3558179 requests in 30.10s, 471.25MB read
Requests/sec: 118212.18
Transfer/sec:     15.66MB
[Lua] latency percentiles: p50=246.00us p95=518.00us p99=824.00us
[Lua] backend markers: coding=3558179 math=0 others=0 unknown=0
[Lua] expected routes: coding=1334365 math=1378784 others=845030 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    20.45ms    2.69ms  31.64ms   64.51%
    Req/Sec   783.42     68.85     1.32k    64.25%
  93616 requests in 30.05s, 12.22MB read
Requests/sec:   3114.88
Transfer/sec:    416.26KB
[Lua] latency percentiles: p50=20280.00us p95=25000.00us p99=26323.00us
[Lua] backend markers: coding=31359 math=31993 others=30264 unknown=0
[Lua] expected routes: coding=35176 math=36285 others=22155 unknown=0
[Lua] aggregate route agreement: 0.913380 (85507/93616); fifo_matches=68288 fifo_mismatches=25328
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    69.13ms   13.96ms 224.55ms   84.05%
    Req/Sec   232.16     40.48   333.00     61.17%
  27759 requests in 30.02s, 10.16MB read
Requests/sec:    924.70
Transfer/sec:    346.60KB
[Lua] latency percentiles: p50=66634.00us p95=87256.00us p99=108411.00us
[Lua] backend markers: coding=9279 math=9507 others=8973 unknown=0
[Lua] expected routes: coding=10412 math=10771 others=6576 unknown=0
[Lua] aggregate route agreement: 0.913650 (25362/27759); fifo_matches=20259 fifo_mismatches=7500
```
