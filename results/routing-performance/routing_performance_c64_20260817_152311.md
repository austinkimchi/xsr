# High-Performance wrk Benchmark Results

- Timestamp: `Mon Aug 17 03:23:11 PM PDT 2026`
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
    Latency   274.75us  144.26us   7.14ms   87.40%
    Req/Sec    30.22k     2.15k   35.79k    68.42%
  3609310 requests in 30.00s, 478.03MB read
Requests/sec: 120298.66
Transfer/sec:     15.93MB
[Lua] latency percentiles: p50=241.00us p95=509.00us p99=801.00us
[Lua] backend markers: coding=3609310 math=0 others=0 unknown=0
[Lua] expected routes: coding=1353531 math=1398616 others=857163 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    20.86ms    3.43ms  31.92ms   65.14%
    Req/Sec   768.22     86.17     0.94k    54.25%
  91802 requests in 30.02s, 11.98MB read
Requests/sec:   3058.34
Transfer/sec:    408.69KB
[Lua] latency percentiles: p50=20008.00us p95=26689.00us p99=28785.00us
[Lua] backend markers: coding=30719 math=31056 others=30027 unknown=0
[Lua] expected routes: coding=34467 math=35631 others=21704 unknown=0
[Lua] aggregate route agreement: 0.909337 (83479/91802); fifo_matches=66597 fifo_mismatches=25205
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    68.53ms   13.68ms 183.63ms   84.64%
    Req/Sec   234.20     38.10   323.00     65.33%
  28000 requests in 30.02s, 10.25MB read
Requests/sec:    932.84
Transfer/sec:    349.67KB
[Lua] latency percentiles: p50=66274.00us p95=85851.00us p99=108105.00us
[Lua] backend markers: coding=9440 math=9512 others=9048 unknown=0
[Lua] expected routes: coding=10570 math=10807 others=6623 unknown=0
[Lua] aggregate route agreement: 0.913393 (25575/28000); fifo_matches=20430 fifo_mismatches=7570
```
