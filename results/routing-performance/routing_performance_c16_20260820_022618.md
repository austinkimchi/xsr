# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 20 02:26:18 AM PDT 2026`
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
    Latency    95.74us   77.99us   6.40ms   96.17%
    Req/Sec    26.62k     3.81k   35.46k    63.29%
  3189038 requests in 30.10s, 422.32MB read
Requests/sec: 105948.66
Transfer/sec:     14.03MB
[Lua] latency percentiles: p50=91.00us p95=165.00us p99=284.00us
[Lua] backend markers: coding=3189038 math=0 others=0 unknown=0
[Lua] expected routes: coding=1195942 math=1235748 others=757348 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     5.38ms    1.47ms  49.50ms   69.11%
    Req/Sec   739.13     78.10     0.90k    62.42%
  88312 requests in 30.01s, 11.52MB read
Requests/sec:   2942.42
Transfer/sec:    393.13KB
[Lua] latency percentiles: p50=5028.00us p95=8131.00us p99=9213.00us
[Lua] backend markers: coding=29475 math=30173 others=28664 unknown=0
[Lua] expected routes: coding=33134 math=34217 others=20961 unknown=0
[Lua] aggregate route agreement: 0.912775 (80609/88312); fifo_matches=64408 fifo_mismatches=23904
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    21.12ms    4.70ms  59.12ms   74.25%
    Req/Sec   189.66     27.89   262.00     58.75%
  22682 requests in 30.02s, 8.32MB read
Requests/sec:    755.65
Transfer/sec:    283.69KB
[Lua] latency percentiles: p50=20643.00us p95=28583.00us p99=33208.00us
[Lua] backend markers: coding=7679 math=7821 others=7182 unknown=0
[Lua] expected routes: coding=8547 math=8847 others=5288 unknown=0
[Lua] aggregate route agreement: 0.916498 (20788/22682); fifo_matches=16577 fifo_mismatches=6105
```
