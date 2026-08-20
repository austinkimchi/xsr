# High-Performance wrk Benchmark Results

- Timestamp: `Mon Aug 17 03:18:38 PM PDT 2026`
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
    Latency    45.59us   45.85us   3.19ms   98.56%
    Req/Sec    30.41k     2.29k   34.76k    62.96%
  3643839 requests in 30.10s, 482.61MB read
Requests/sec: 121057.66
Transfer/sec:     16.03MB
[Lua] latency percentiles: p50=41.00us p95=65.00us p99=106.00us
[Lua] backend markers: coding=3643839 math=0 others=0 unknown=0
[Lua] expected routes: coding=1366491 math=1412001 others=865347 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.48ms    1.12ms  16.34ms   80.47%
    Req/Sec   787.44    115.14     1.36k    70.78%
  94200 requests in 30.10s, 12.29MB read
Requests/sec:   3129.70
Transfer/sec:    418.27KB
[Lua] latency percentiles: p50=2213.00us p95=4750.00us p99=6598.00us
[Lua] backend markers: coding=31501 math=31784 others=30915 unknown=0
[Lua] expected routes: coding=35381 math=36493 others=22326 unknown=0
[Lua] aggregate route agreement: 0.908822 (85611/94200); fifo_matches=68317 fifo_mismatches=25883
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.49ms    2.31ms  24.84ms   70.04%
    Req/Sec   235.33     34.60   313.00     60.50%
  28132 requests in 30.02s, 10.30MB read
Requests/sec:    937.15
Transfer/sec:    351.44KB
[Lua] latency percentiles: p50=8342.00us p95=12463.00us p99=14443.00us
[Lua] backend markers: coding=9572 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10666 math=10837 others=6629 unknown=0
[Lua] aggregate route agreement: 0.914013 (25713/28132); fifo_matches=20526 fifo_mismatches=7606
```
