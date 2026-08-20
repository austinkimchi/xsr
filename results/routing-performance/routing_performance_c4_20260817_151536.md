# High-Performance wrk Benchmark Results

- Timestamp: `Mon Aug 17 03:15:36 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `4`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/3] Direct Backend
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18391/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    25.03us   16.01us   3.13ms   98.87%
    Req/Sec    21.85k     1.11k   24.77k    70.80%
  2613747 requests in 30.10s, 346.06MB read
Requests/sec:  86838.22
Transfer/sec:     11.50MB
[Lua] latency percentiles: p50=24.00us p95=33.00us p99=42.00us
[Lua] backend markers: coding=2613747 math=0 others=0 unknown=0
[Lua] expected routes: coding=980200 math=1012828 others=620719 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.46ms  539.20us   4.19ms   67.21%
    Req/Sec   672.74     75.98     0.97k    57.17%
  80435 requests in 30.04s, 10.49MB read
Requests/sec:   2677.35
Transfer/sec:    357.60KB
[Lua] latency percentiles: p50=1404.00us p95=2416.00us p99=2836.00us
[Lua] backend markers: coding=26879 math=27205 others=26351 unknown=0
[Lua] expected routes: coding=30185 math=31210 others=19040 unknown=0
[Lua] aggregate route agreement: 0.909107 (73124/80435); fifo_matches=58349 fifo_mismatches=22086
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.35ms    1.46ms  14.07ms   67.20%
    Req/Sec   228.91     30.44   290.00     60.92%
  27369 requests in 30.02s, 10.03MB read
Requests/sec:    911.75
Transfer/sec:    342.11KB
[Lua] latency percentiles: p50=4200.00us p95=6973.00us p99=8144.00us
[Lua] backend markers: coding=9279 math=9354 others=8736 unknown=0
[Lua] expected routes: coding=10335 math=10613 others=6421 unknown=0
[Lua] aggregate route agreement: 0.915415 (25054/27369); fifo_matches=19984 fifo_mismatches=7385
```
