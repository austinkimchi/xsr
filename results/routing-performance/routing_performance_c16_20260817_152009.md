# High-Performance wrk Benchmark Results

- Timestamp: `Mon Aug 17 03:20:09 PM PDT 2026`
- Tool: `wrk`
- Threads: `4`
- Connections: `16`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/3] Direct Backend
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18391/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    82.26us   71.60us   6.02ms   97.01%
    Req/Sec    30.99k     2.08k   35.80k    67.30%
  3707203 requests in 30.10s, 491.01MB read
Requests/sec: 123166.13
Transfer/sec:     16.31MB
[Lua] latency percentiles: p50=81.00us p95=135.00us p99=256.00us
[Lua] backend markers: coding=3707203 math=0 others=0 unknown=0
[Lua] expected routes: coding=1390259 math=1436526 others=880418 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.88ms    1.31ms  30.31ms   69.40%
    Req/Sec   814.69     81.91     0.98k    57.83%
  97346 requests in 30.02s, 12.71MB read
Requests/sec:   3243.16
Transfer/sec:    433.49KB
[Lua] latency percentiles: p50=4532.00us p95=7469.00us p99=8124.00us
[Lua] backend markers: coding=32620 math=32810 others=31916 unknown=0
[Lua] expected routes: coding=36596 math=37694 others=23056 unknown=0
[Lua] aggregate route agreement: 0.908984 (88486/97346); fifo_matches=70597 fifo_mismatches=26749
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    17.13ms    3.95ms  46.37ms   73.12%
    Req/Sec   233.91     33.72   323.00     57.83%
  27968 requests in 30.02s, 10.24MB read
Requests/sec:    931.68
Transfer/sec:    349.20KB
[Lua] latency percentiles: p50=16762.00us p95=23559.00us p99=27138.00us
[Lua] backend markers: coding=9408 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10545 math=10802 others=6621 unknown=0
[Lua] aggregate route agreement: 0.913222 (25541/27968); fifo_matches=20405 fifo_mismatches=7563
```
