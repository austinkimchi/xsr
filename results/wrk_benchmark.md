# High-Performance XDP vs. vLLM-SR Benchmark Report

This markdown summarizes the load testing results comparing `xsr` against `vllm-sr` across varying concurrency levels ($c = 1, 2, 4, 8, 10, 16, 32$).
Both XDP and vllm-sr execute the shared literal keyword policy, matching 13 case-insensitive substring matching across 13 domain keywords to route prompts into `coding`, `math`, and `others` routes.

---

## Summary

| Concurrency ($c$) | Threads ($t$) | XDP RPS           | XDP Avg Latency | vLLM-SR RPS   | vLLM-SR Avg Latency | XDP Throughput Speedup  | XDP Latency Speedup |
| :---:             | :---:         | :---:             | :---:           | :---:         | :---:               | :---:                   | :---:               |
| **c = 1**         | 1             | **13,685.10 RPS** | **0.08 ms**     | 753.32 RPS    | 1.32 ms             | **18.2×**               | **16.0×**           |
| **c = 2**         | 2             | **15,449.43 RPS** | **0.14 ms**     | 1,273.11 RPS  | 1.57 ms             | **12.1×**               | **11.5×**           |
| **c = 4**         | 4             | **18,540.85 RPS** | **0.22 ms**     | 1,699.32 RPS  | 2.35 ms             | **10.9×**               | **10.6×**           |
| **c = 8**         | 4             | **18,978.30 RPS** | **0.41 ms**     | 1,224.75 RPS  | 1.71 ms             | **15.5×**               | **4.1×**            |
| **c = 10**        | 4             | **17,621.70 RPS** | **0.44 ms**     | 1,283.82 RPS  | 1.63 ms             | **13.7×**               | **3.7×**            |
| **c = 16**        | 4             | **18,317.89 RPS** | **0.88 ms**     | 1,863.66 RPS  | 2.10 ms             | **9.8×**                | **2.4×**            |
| **c = 32**        | 4             | **18,538.90 RPS** | **0.86 ms**     | 1,783.94 RPS  | 2.35 ms             | **10.4×**               | **2.7×**            |

---

## Detailed Benchmark Results

### Concurrency 1 (c=1, t=1)
* **XDP Throughput**: `13,685.10 RPS` | **Avg Latency**: `82.50 us`
* **vLLM-SR Throughput**: `753.32 RPS` | **Avg Latency**: `1.32 ms`
* **Speedup**: `18.2×` Throughput | `16.0×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    82.50us  124.12us   4.19ms   95.00%
    Req/Sec    13.75k     0.91k   14.51k    94.06%
  138217 requests in 10.10s, 21.49MB read
Requests/sec:  13685.10

--- [2/2] vLLM-SR Route ---
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.32ms  257.19us   6.48ms   89.78%
    Req/Sec   756.85     36.61   828.00     78.00%
  7539 requests in 10.01s, 2.95MB read
Requests/sec:    753.32
```

---

### Concurrency 2 (c=2, t=2)
* **XDP Throughput**: `15,449.43 RPS` | **Avg Latency**: `137.09 us`
* **vLLM-SR Throughput**: `1,273.11 RPS` | **Avg Latency**: `1.57 ms`
* **Speedup**: `12.1×` Throughput | `11.5×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   137.09us  128.05us   4.39ms   92.46%
    Req/Sec     7.80k   698.50    13.28k    93.53%
  156026 requests in 10.10s, 24.25MB read
Requests/sec:  15449.43

--- [2/2] vLLM-SR Route ---
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.57ms  317.27us  11.60ms   91.32%
    Req/Sec   639.66     29.43   686.00     79.00%
  12736 requests in 10.00s, 4.98MB read
Requests/sec:   1273.11
```

---

### Concurrency 4 (c=4, t=4)
* **XDP Throughput**: `18,540.85 RPS` | **Avg Latency**: `221.82 us`
* **vLLM-SR Throughput**: `1,699.32 RPS` | **Avg Latency**: `2.35 ms`
* **Speedup**: `10.9×` Throughput | `10.6×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   221.82us  159.48us   4.39ms   90.27%
    Req/Sec     4.66k   105.21     4.87k    71.78%
  187257 requests in 10.10s, 29.11MB read
Requests/sec:  18540.85

--- [2/2] vLLM-SR Route ---
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.35ms  580.31us  12.57ms   65.87%
    Req/Sec   426.84     87.71   616.00     74.00%
  17006 requests in 10.01s, 6.65MB read
Requests/sec:   1699.32
```

---

### Concurrency 8 (c=8, t=4)
* **XDP Throughput**: `18,978.30 RPS` | **Avg Latency**: `414.00 us`
* **vLLM-SR Throughput**: `1,224.75 RPS` | **Avg Latency**: `1.71 ms`
* **Speedup**: `15.5×` Throughput | `4.1×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   414.00us  244.78us   5.09ms   87.20%
    Req/Sec     4.79k   536.04     9.04k    84.08%
  191669 requests in 10.10s, 29.79MB read
Requests/sec:  18978.30

--- [2/2] vLLM-SR Route ---
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.71ms  505.08us  10.55ms   93.08%
    Req/Sec   603.40     45.01   686.00     69.12%
  12260 requests in 10.01s, 4.80MB read
Requests/sec:   1224.75
```

---

### Concurrency 10 (c=10, t=4)
* **XDP Throughput**: `17,621.70 RPS` | **Avg Latency**: `437.81 us`
* **vLLM-SR Throughput**: `1,283.82 RPS` | **Avg Latency**: `1.63 ms`
* **Speedup**: `13.7×` Throughput | `3.7×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   437.81us  250.18us   5.37ms   85.82%
    Req/Sec     4.46k   691.38    16.51k    95.76%
  177973 requests in 10.10s, 27.67MB read
Requests/sec:  17621.70

--- [2/2] vLLM-SR Route ---
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.63ms  464.45us   9.73ms   93.18%
    Req/Sec     1.22k   204.39     1.36k    92.45%
  12851 requests in 10.01s, 5.03MB read
Requests/sec:   1283.82
```

---

### Concurrency 16 (c=16, t=4)
* **XDP Throughput**: `18,317.89 RPS` | **Avg Latency**: `0.88 ms`
* **vLLM-SR Throughput**: `1,863.66 RPS` | **Avg Latency**: `2.10 ms`
* **Speedup**: `9.8×` Throughput | `2.4×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     0.88ms  452.40us  16.06ms   94.47%
    Req/Sec     4.61k   162.35     5.77k    78.25%
  183413 requests in 10.01s, 28.51MB read
Requests/sec:  18317.89

--- [2/2] vLLM-SR Route ---
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.10ms  451.82us   7.93ms   76.31%
    Req/Sec     463.66   31.12    512.00     82.10%
Requests/sec:   1863.66
```

---

### Concurrency 32 (c=32, t=4)
* **XDP Throughput**: `18,538.90 RPS` | **Avg Latency**: `0.86 ms`
* **vLLM-SR Throughput**: `1,783.94 RPS` | **Avg Latency**: `2.35 ms`
* **Speedup**: `10.4×` Throughput | `2.7×` Latency

```text
--- [1/2] XDP Route (via netns) ---
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     0.86ms  462.55us  18.58ms   93.40%
    Req/Sec     6.25k     2.29k   14.95k    65.12%
  187238 requests in 10.10s, 29.11MB read
Requests/sec:  18538.90

--- [2/2] vLLM-SR Route ---
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.35ms    0.88ms  15.64ms   91.30%
    Req/Sec     445.00   24.10    480.00     80.00%
Requests/sec:   1783.94
```

---

## Architectural Takeaways

1. **Throughput Scaling**: XDP consistently maintains **~17,600 – 19,000 RPS** across all concurrency levels above 4, whereas vLLM-SR caps around **1,700 – 1,860 RPS**.
2. **Sub-millisecond Latency**: XDP delivers **sub-millisecond average latency** across all concurrency levels ($82.5\mu\text{s}$ at $c=1$ to $880\mu\text{s}$ at $c=16$), whereas vLLM-SR requires **1.32ms – 2.35ms**.
3. **Efficiency Gap**: XDP achieves an overall **~10× to 18.2× throughput speedup** and **~2.4× to 16.0× latency speedup** (up to **16.0×** lower average latency at $c=1$) compared to application-layer HTTP semantic routing.
