# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 20 02:20:17 AM PDT 2026`
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
    Latency    23.19us   28.20us   3.19ms   99.37%
    Req/Sec    24.51k     1.41k   27.75k    67.77%
  1467974 requests in 30.10s, 194.38MB read
Requests/sec:  48770.47
Transfer/sec:      6.46MB
[Lua] latency percentiles: p50=22.00us p95=31.00us p99=44.00us
[Lua] backend markers: coding=1467974 math=0 others=0 unknown=0
[Lua] expected routes: coding=550534 math=568819 others=348621 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   734.07us  326.06us   4.46ms   71.02%
    Req/Sec     1.33k    87.29     1.62k    68.17%
  79493 requests in 30.01s, 10.39MB read
Requests/sec:   2649.05
Transfer/sec:    354.51KB
[Lua] latency percentiles: p50=697.00us p95=1340.00us p99=1723.00us
[Lua] backend markers: coding=26533 math=27142 others=25818 unknown=0
[Lua] expected routes: coding=29832 math=30789 others=18872 unknown=0
[Lua] aggregate route agreement: 0.912621 (72547/79493); fifo_matches=57967 fifo_mismatches=21526
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.75ms    0.88ms   7.13ms   66.85%
    Req/Sec   360.93     32.70   450.00     69.17%
  21570 requests in 30.01s, 7.90MB read
Requests/sec:    718.64
Transfer/sec:    269.39KB
[Lua] latency percentiles: p50=2633.00us p95=4342.00us p99=5154.00us
[Lua] backend markers: coding=7199 math=7378 others=6993 unknown=0
[Lua] expected routes: coding=8088 math=8364 others=5118 unknown=0
[Lua] aggregate route agreement: 0.913074 (19695/21570); fifo_matches=15735 fifo_mismatches=5835
```
