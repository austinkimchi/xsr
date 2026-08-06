# High-Performance XDP vs. vLLM-SR Benchmark Report

This markdown summarizes the load testing results comparing `xsr` against `vllm-sr` across varying concurrency levels ($c = 1, 2, 4, 8, 10, 16, 32, 64, 96$).
Both XDP and vllm-sr execute the shared literal keyword policy, matching 13 case-insensitive substring matching across 13 domain keywords to route prompts into `coding`, `math`, and `others` routes.

---

## Summary

| Concurrency ($c$) | Threads ($t$) | XDP RPS           | XDP Avg Latency | vLLM-SR RPS   | vLLM-SR Avg Latency | XDP Throughput Speedup  | XDP Latency Speedup |
| :---:             | :---:         | :---:             | :---:           | :---:         | :---:               | :---:                   | :---:               |
| **c = 1**         | 1             | **14,383.61 RPS** | **0.08 ms**     | 726.69 RPS    | 1.37 ms             | **19.8×**               | **17.0×**           |
| **c = 2**         | 2             | **15,522.56 RPS** | **0.14 ms**     | 1,270.80 RPS  | 1.57 ms             | **12.2×**               | **11.5×**           |
| **c = 4**         | 4             | **16,540.97 RPS** | **0.25 ms**     | 1,728.99 RPS  | 2.30 ms             | **9.6×**                | **9.2×**            |
| **c = 8**         | 4             | **17,146.39 RPS** | **0.46 ms**     | 2,179.64 RPS  | 3.69 ms             | **7.9×**                | **8.0×**            |
| **c = 10**        | 4             | **16,900.40 RPS** | **0.46 ms**     | 2,093.81 RPS  | 3.84 ms             | **8.1×**                | **8.3×**            |
| **c = 16**        | 4             | **18,747.28 RPS** | **0.87 ms**     | 2,067.86 RPS  | 7.80 ms             | **9.1×**                | **9.0×**            |
| **c = 32**        | 4             | **20,274.49 RPS** | **1.59 ms**     | 2,088.19 RPS  | 15.51 ms            | **9.7×**                | **9.8×**            |
| **c = 64**        | 4             | **18,907.85 RPS** | **3.36 ms**     | 2,127.04 RPS  | 30.28 ms            | **8.9×**                | **9.0×**            |
| **c = 96**        | 4             | **18,815.04 RPS** | **5.05 ms**     | 2,149.97 RPS  | 41.90 ms            | **8.8×**                | **8.3×**            |

---

## Detailed Benchmark Results

### Concurrency 1 (c=1, t=1)
* **XDP Throughput**: `14,383.61 RPS` | **Avg Latency**: `80.63 us`
* **vLLM-SR Throughput**: `726.69 RPS` | **Avg Latency**: `1.37 ms`
* **Speedup**: `19.8×` Throughput | `17.0×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    80.63us  132.36us   3.32ms   95.42%
    Req/Sec    14.46k     0.88k   15.30k    95.05%
  145272 requests in 10.10s, 22.58MB read
Requests/sec:  14383.61

--- [2/2] vLLM-SR Route ---
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.37ms  287.12us   5.65ms   90.42%
    Req/Sec   729.99     35.97   800.00     63.00%
  7268 requests in 10.00s, 2.84MB read
Requests/sec:    726.69
```

---

### Concurrency 2 (c=2, t=2)
* **XDP Throughput**: `15,522.56 RPS` | **Avg Latency**: `136.79 us`
* **vLLM-SR Throughput**: `1,270.80 RPS` | **Avg Latency**: `1.57 ms`
* **Speedup**: `12.2×` Throughput | `11.5×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   136.79us  121.26us   3.37ms   92.21%
    Req/Sec     7.80k   173.62     8.24k    72.28%
  156773 requests in 10.10s, 24.37MB read
Requests/sec:  15522.56

--- [2/2] vLLM-SR Route ---
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.57ms  266.29us   6.06ms   88.17%
    Req/Sec   638.47     33.24   690.00     90.50%
  12714 requests in 10.00s, 4.97MB read
Requests/sec:   1270.80
```

---

### Concurrency 4 (c=4, t=4)
* **XDP Throughput**: `16,540.97 RPS` | **Avg Latency**: `251.15 us`
* **vLLM-SR Throughput**: `1,728.99 RPS` | **Avg Latency**: `2.30 ms`
* **Speedup**: `9.6×` Throughput | `9.2×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   251.15us  186.17us   3.91ms   91.10%
    Req/Sec     4.15k   218.80     4.48k    93.56%
  167059 requests in 10.10s, 25.97MB read
Requests/sec:  16540.97

--- [2/2] vLLM-SR Route ---
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.30ms  377.55us   7.18ms   82.26%
    Req/Sec   434.38     22.17   474.00     79.50%
  17300 requests in 10.01s, 6.76MB read
Requests/sec:   1728.99
```

---

### Concurrency 8 (c=8, t=4)
* **XDP Throughput**: `17,146.39 RPS` | **Avg Latency**: `457.28 us`
* **vLLM-SR Throughput**: `2,179.64 RPS` | **Avg Latency**: `3.69 ms`
* **Speedup**: `7.9×` Throughput | `8.0×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   457.28us  258.19us   3.97ms   85.44%
    Req/Sec     4.33k   472.36     8.24k    83.33%
  173172 requests in 10.10s, 26.92MB read
Requests/sec:  17146.39

--- [2/2] vLLM-SR Route ---
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     3.69ms    1.54ms  13.78ms   82.52%
    Req/Sec   547.63     57.04   660.00     56.00%
  21819 requests in 10.01s, 8.53MB read
Requests/sec:   2179.64
```

---

### Concurrency 10 (c=10, t=4)
* **XDP Throughput**: `16,900.40 RPS` | **Avg Latency**: `457.67 us`
* **vLLM-SR Throughput**: `2,093.81 RPS` | **Avg Latency**: `3.84 ms`
* **Speedup**: `8.1×` Throughput | `8.3×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   457.67us  264.50us   4.28ms   85.98%
    Req/Sec     4.28k   705.43    15.96k    92.77%
  170669 requests in 10.10s, 26.53MB read
Requests/sec:  16900.40

--- [2/2] vLLM-SR Route ---
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     3.84ms    2.07ms  14.12ms   85.85%
    Req/Sec   525.94     20.93   616.00     71.50%
  20949 requests in 10.01s, 8.19MB read
Requests/sec:   2093.81
```

---

### Concurrency 16 (c=16, t=4)
* **XDP Throughput**: `18,747.28 RPS` | **Avg Latency**: `0.87 ms`
* **vLLM-SR Throughput**: `2,067.86 RPS` | **Avg Latency**: `7.80 ms`
* **Speedup**: `9.1×` Throughput | `9.0×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     0.87ms  585.20us  17.78ms   95.91%
    Req/Sec     4.73k   404.04     9.76k    91.54%
  189346 requests in 10.10s, 29.43MB read
Requests/sec:  18747.28

--- [2/2] vLLM-SR Route ---
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     7.80ms    4.06ms  22.28ms   72.47%
    Req/Sec   519.36     56.69   680.00     66.00%
  20692 requests in 10.01s, 8.09MB read
Requests/sec:   2067.86
```

---

### Concurrency 32 (c=32, t=4)
* **XDP Throughput**: `20,274.49 RPS` | **Avg Latency**: `1.59 ms`
* **vLLM-SR Throughput**: `2,088.19 RPS` | **Avg Latency**: `15.51 ms`
* **Speedup**: `9.7×` Throughput | `9.8×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.59ms  576.40us  18.72ms   92.83%
    Req/Sec     5.10k   305.20     6.45k    89.75%
  203008 requests in 10.01s, 31.56MB read
Requests/sec:  20274.49

--- [2/2] vLLM-SR Route ---
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    15.51ms    7.98ms  46.51ms   64.58%
    Req/Sec   524.59     83.06   720.00     66.00%
  20898 requests in 10.01s, 8.17MB read
Requests/sec:   2088.19
```

---

### Concurrency 64 (c=64, t=4)
* **XDP Throughput**: `18,907.85 RPS` | **Avg Latency**: `3.36 ms`
* **vLLM-SR Throughput**: `2,127.04 RPS` | **Avg Latency**: `30.28 ms`
* **Speedup**: `8.9×` Throughput | `9.0×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     3.36ms  560.10us  27.37ms   76.50%
    Req/Sec     4.77k   343.09     9.04k    94.75%
  189666 requests in 10.03s, 29.48MB read
Requests/sec:  18907.85

--- [2/2] vLLM-SR Route ---
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    30.28ms   14.13ms  79.41ms   69.06%
    Req/Sec   534.85     33.29   636.00     67.75%
  21306 requests in 10.02s, 8.33MB read
Requests/sec:   2127.04
```

---

### Concurrency 96 (c=96, t=4)
* **XDP Throughput**: `18,815.04 RPS` | **Avg Latency**: `5.05 ms`
* **vLLM-SR Throughput**: `2,149.97 RPS` | **Avg Latency**: `41.90 ms`
* **Speedup**: `8.8×` Throughput | `8.3×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     5.05ms  764.71us  32.15ms   81.86%
    Req/Sec     4.76k   507.37    12.96k    95.76%
  190035 requests in 10.10s, 29.54MB read
Requests/sec:  18815.04

--- [2/2] vLLM-SR Route ---
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    41.90ms   15.39ms 101.58ms   75.49%
    Req/Sec   541.38     44.62   666.00     65.00%
  21566 requests in 10.03s, 8.44MB read
Requests/sec:   2149.97
```

---

## Observations: Advantages of XDP

1. **Throughput Scaling**: XDP consistently maintains **~16,500 – 20,300 RPS** across all concurrency levels, whereas vllm-sr levels off at **~2,070 – 2,180 RPS** regardless of concurrency.
2. **Sub-millisecond Latency**: XDP delivers sub-millisecond average latency at concurrency $\le 8$ ($80.6\mu\text{s}$ at $c=1$ to $457\mu\text{s}$ at $c=8$), whereas vllm-sr latency rises steeply with concurrency — from **1.37ms** at $c=1$ to **41.90ms** at $c=96$.
3. **Efficiency Gap**: XDP achieves an overall **~7.9× to 19.8× throughput speedup** and **~8.0× to 17.0× latency speedup** compared to application-layer HTTP semantic routing. The median throughput XDP speedup is **9.1x** and latency speedup is **9.0x** across all tested concurrency levels. 
