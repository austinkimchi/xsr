# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 20 02:21:47 AM PDT 2026`
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
    Latency    25.35us   21.01us   3.18ms   99.34%
    Req/Sec    21.60k     1.22k   24.53k    72.67%
  2587537 requests in 30.10s, 342.58MB read
Requests/sec:  85964.28
Transfer/sec:     11.38MB
[Lua] latency percentiles: p50=24.00us p95=34.00us p99=43.00us
[Lua] backend markers: coding=2587537 math=0 others=0 unknown=0
[Lua] expected routes: coding=970376 math=1002684 others=614477 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.44ms  529.31us   5.62ms   67.00%
    Req/Sec   678.53     77.40     0.87k    54.42%
  81120 requests in 30.03s, 10.58MB read
Requests/sec:   2701.25
Transfer/sec:    360.79KB
[Lua] latency percentiles: p50=1392.00us p95=2394.00us p99=2787.00us
[Lua] backend markers: coding=27199 math=27713 others=26208 unknown=0
[Lua] expected routes: coding=30495 math=31437 others=19188 unknown=0
[Lua] aggregate route agreement: 0.913462 (74100/81120); fifo_matches=59176 fifo_mismatches=21944
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.38ms    1.45ms  13.78ms   66.78%
    Req/Sec   227.16     31.16   300.00     62.33%
  27157 requests in 30.02s, 9.95MB read
Requests/sec:    904.72
Transfer/sec:    339.27KB
[Lua] latency percentiles: p50=4271.00us p95=6933.00us p99=8146.00us
[Lua] backend markers: coding=9237 math=9184 others=8736 unknown=0
[Lua] expected routes: coding=10296 math=10460 others=6401 unknown=0
[Lua] aggregate route agreement: 0.914018 (24822/27157); fifo_matches=19816 fifo_mismatches=7341
```
