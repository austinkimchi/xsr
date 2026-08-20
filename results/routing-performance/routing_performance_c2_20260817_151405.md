# High-Performance wrk Benchmark Results

- Timestamp: `Mon Aug 17 03:14:05 PM PDT 2026`
- Tool: `wrk`
- Threads: `2`
- Connections: `2`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/3] Direct Backend
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18391/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    22.83us   22.76us   3.18ms   99.22%
    Req/Sec    24.84k     1.30k   27.70k    66.94%
  1487888 requests in 30.10s, 197.02MB read
Requests/sec:  49431.55
Transfer/sec:      6.55MB
[Lua] latency percentiles: p50=22.00us p95=30.00us p99=42.00us
[Lua] backend markers: coding=1487888 math=0 others=0 unknown=0
[Lua] expected routes: coding=557969 math=576572 others=353347 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   750.37us  339.22us   2.51ms   70.42%
    Req/Sec     1.30k   100.44     1.55k    66.17%
  77887 requests in 30.01s, 10.18MB read
Requests/sec:   2595.35
Transfer/sec:    347.33KB
[Lua] latency percentiles: p50=711.00us p95=1385.00us p99=1784.00us
[Lua] backend markers: coding=26047 math=26244 others=25596 unknown=0
[Lua] expected routes: coding=29260 math=30151 others=18476 unknown=0
[Lua] aggregate route agreement: 0.908586 (70767/77887); fifo_matches=56476 fifo_mismatches=21411
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.73ms    0.87ms   7.25ms   66.41%
    Req/Sec   362.76     30.36   450.00     67.17%
  21674 requests in 30.02s, 7.94MB read
Requests/sec:    722.10
Transfer/sec:    270.71KB
[Lua] latency percentiles: p50=2620.00us p95=4312.00us p99=5112.00us
[Lua] backend markers: coding=7274 math=7380 others=7020 unknown=0
[Lua] expected routes: coding=8162 math=8376 others=5136 unknown=0
[Lua] aggregate route agreement: 0.913076 (19790/21674); fifo_matches=15812 fifo_mismatches=5862
```
