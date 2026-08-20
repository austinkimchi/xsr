# High-Performance wrk Benchmark Results

- Timestamp: `Thu Aug 20 02:18:47 AM PDT 2026`
- Tool: `wrk`
- Threads: `1`
- Connections: `1`
- Duration: `30s`

- Routing backend ports: coding=`18391`, math=`18392`, others=`18393`

## [1/3] Direct Backend
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18391/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    21.87us   34.36us   3.18ms   99.44%
    Req/Sec    26.48k     1.94k   29.34k    71.67%
  790157 requests in 30.00s, 104.64MB read
Requests/sec:  26338.31
Transfer/sec:      3.49MB
[Lua] latency percentiles: p50=19.00us p95=30.00us p99=45.00us
[Lua] backend markers: coding=790157 math=0 others=0 unknown=0
[Lua] expected routes: coding=296339 math=306169 others=187649 unknown=0
[Lua] backend marker agreement: skipped for this target; backend markers reflect configured upstream endpoints, not necessarily logical route selection
```

Starting routing proxy...
## [2/3] XSR/XDP Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:18081/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   383.88us  184.80us   3.63ms   65.91%
    Req/Sec     2.51k    71.60     2.69k    74.00%
  74974 requests in 30.00s, 9.81MB read
Requests/sec:   2499.03
Transfer/sec:    334.76KB
[Lua] latency percentiles: p50=357.00us p95=707.00us p99=878.00us
[Lua] backend markers: coding=25039 math=25599 others=24336 unknown=0
[Lua] expected routes: coding=28141 math=29043 others=17790 unknown=0
[Lua] aggregate route agreement: 0.912690 (68428/74974); fifo_matches=54673 fifo_mismatches=20301
```

## [3/3] vLLM-SR Route
```
[Lua] Loaded 240 prompts from /home/pkimchi/ebpf-router-test/tools/XDP/benchmarks/routing_wrk/../dataset_prompts.jsonl
Running 30s test @ http://10.10.0.1:8899/v1/chat/completions
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.35ms  761.44us   5.56ms   65.27%
    Req/Sec   419.75     37.42   510.00     66.67%
  12540 requests in 30.01s, 4.59MB read
Requests/sec:    417.84
Transfer/sec:    156.72KB
[Lua] latency percentiles: p50=2231.00us p95=3742.00us p99=4366.00us
[Lua] backend markers: coding=4220 math=4264 others=4056 unknown=0
[Lua] expected routes: coding=4728 math=4844 others=2968 unknown=0
[Lua] aggregate route agreement: 0.913238 (11452/12540); fifo_matches=9148 fifo_mismatches=3392
```
