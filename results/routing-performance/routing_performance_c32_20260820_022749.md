# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 20 02:27:49 AM PDT 2026`
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
    Latency   167.89us  105.17us   7.59ms   86.50%
    Req/Sec    25.82k     3.34k   36.25k    71.51%
  3093017 requests in 30.10s, 409.59MB read
Requests/sec: 102758.12
Transfer/sec:     13.61MB
[Lua] latency percentiles: p50=142.00us p95=321.00us p99=517.00us
[Lua] backend markers: coding=3093017 math=0 others=0 unknown=0
[Lua] expected routes: coding=1159923 math=1198552 others=734542 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     9.47ms    1.79ms  58.60ms   63.69%
    Req/Sec   844.18     81.10     1.01k    56.83%
  100870 requests in 30.03s, 13.17MB read
Requests/sec:   3358.89
Transfer/sec:    448.98KB
[Lua] latency percentiles: p50=9283.00us p95=12416.00us p99=14450.00us
[Lua] backend markers: coding=33682 math=34439 others=32749 unknown=0
[Lua] expected routes: coding=37862 math=39067 others=23941 unknown=0
[Lua] aggregate route agreement: 0.912680 (92062/100870); fifo_matches=73561 fifo_mismatches=27309
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    34.41ms    7.43ms  94.43ms   79.85%
    Req/Sec   233.18     34.97   323.00     64.92%
  27880 requests in 30.02s, 10.20MB read
Requests/sec:    928.77
Transfer/sec:    348.01KB
[Lua] latency percentiles: p50=33088.00us p95=45500.00us p99=54297.00us
[Lua] backend markers: coding=9320 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10475 math=10789 others=6616 unknown=0
[Lua] aggregate route agreement: 0.912769 (25448/27880); fifo_matches=20335 fifo_mismatches=7545
```
