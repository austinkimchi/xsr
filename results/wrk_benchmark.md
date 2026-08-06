# XDP vs. vllm-sr Benchmark Summary

This markdown summarizes the load testing results comparing `xsr` against `vllm-sr` across varying concurrency levels (1, 2, 4, 8, 10, 16, 32, 64, 96).
Both XDP and vllm-sr execute the shared ngram keyword policy, matching 13 case-insensitive substring matching across 13 domain keywords to route prompts into `coding`, `math`, and `others` routes.

---

## Summary

| Concurrency (c) | Threads (t) | XDP RPS           | XDP Avg Latency | vLLM-SR RPS   | vLLM-SR Avg Latency | XDP Throughput Speedup  | XDP Latency Speedup |
| :---:             | :---:         | :---:             | :---:           | :---:         | :---:               | :---:                   | :---:               |
| 1                 | 1             | 7,474.02          | 0.12 ms         | 414.81        | 2.37 ms             | 18.0×                   | 20.4×               |
| 2                 | 2             | 12,634.41         | 0.14 ms         | 717.42        | 2.75 ms             | 17.6×                   | 20.1×               |
| 4                 | 4             | 17,445.58         | 0.20 ms         | 906.42        | 4.37 ms             | 19.2×                   | 21.6×               |
| 8                 | 4             | 21,642.27         | 0.33 ms         | 932.49        | 8.54 ms             | 23.2×                   | 26.1×               |
| 10                | 4             | 21,592.17         | 0.33 ms         | 931.71        | 8.54 ms             | 23.2×                   | 26.0×               |
| 16                | 4             | 25,344.87         | 0.60 ms         | 926.63        | 17.23 ms            | 27.4×                   | 28.9×               |
| 32                | 4             | 25,457.04         | 1.21 ms         | 924.59        | 34.58 ms            | 27.5×                   | 28.6×               |
| 64                | 4             | 19,786.41         | 3.18 ms         | 747.11        | 85.51 ms            | 26.5×                   | 26.9×               |
| 96                | 4             | 21,582.43         | 4.39 ms         | 929.65        | 103.02 ms           | 23.2×                   | 23.5×               |

---

## Detailed Benchmark Results

### Concurrency 1 (c=1, t=1)
* **XDP Throughput**: `7,474.02 RPS` | **Avg Latency**: `116.25 us`
* **vLLM-SR Throughput**: `414.81 RPS` | **Avg Latency**: `2.37 ms`
* **Speedup**: `18.0×` Throughput | `20.4×` Latency

```text
--- [1/2] XDP Route ---
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   116.25us   44.57us   3.16ms   96.26%
    Req/Sec     7.51k   259.51     8.11k    70.76%
  224968 requests in 30.10s, 29.55MB read
Requests/sec:   7474.02

--- [2/2] vLLM-SR Route ---
  1 threads and 1 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.37ms  752.94us   7.25ms   65.28%
    Req/Sec   416.70     37.91   505.00     69.67%
  12449 requests in 30.01s, 4.56MB read
Requests/sec:    414.81
```

---

### Concurrency 2 (c=2, t=2)
* **XDP Throughput**: `12,634.41 RPS` | **Avg Latency**: `136.85 us`
* **vLLM-SR Throughput**: `717.42 RPS` | **Avg Latency**: `2.75 ms`
* **Speedup**: `17.6×` Throughput | `20.1×` Latency

```text
--- [1/2] XDP Route ---
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   136.85us   45.72us   3.31ms   86.92%
    Req/Sec     6.35k   179.60     6.82k    75.58%
  380292 requests in 30.10s, 49.91MB read
Requests/sec:  12634.41

--- [2/2] vLLM-SR Route ---
  2 threads and 2 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     2.75ms    0.88ms   7.70ms   67.07%
    Req/Sec   360.30     32.40   434.00     67.50%
  21532 requests in 30.01s, 7.88MB read
Requests/sec:    717.42
```

---

### Concurrency 4 (c=4, t=4)
* **XDP Throughput**: `17,445.58 RPS` | **Avg Latency**: `201.94 us`
* **vLLM-SR Throughput**: `906.42 RPS` | **Avg Latency**: `4.37 ms`
* **Speedup**: `19.2×` Throughput | `21.6×` Latency

```text
--- [1/2] XDP Route ---
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   201.94us   58.72us   3.97ms   73.93%
    Req/Sec     4.38k   170.77     4.79k    82.81%
  525104 requests in 30.10s, 68.79MB read
Requests/sec:  17445.58

--- [2/2] vLLM-SR Route ---
  4 threads and 4 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.37ms    1.42ms  11.81ms   66.89%
    Req/Sec   227.57     30.32   300.00     61.08%
  27212 requests in 30.02s, 9.97MB read
Requests/sec:    906.42
```

---

### Concurrency 8 (c=8, t=4)
* **XDP Throughput**: `21,642.27 RPS` | **Avg Latency**: `327.24 us`
* **vLLM-SR Throughput**: `932.49 RPS` | **Avg Latency**: `8.54 ms`
* **Speedup**: `23.2×` Throughput | `26.1×` Latency

```text
--- [1/2] XDP Route ---
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   327.24us  115.26us   3.65ms   78.61%
    Req/Sec     5.44k   193.40     7.13k    83.71%
  651430 requests in 30.10s, 85.44MB read
Requests/sec:  21642.27

--- [2/2] vLLM-SR Route ---
  4 threads and 8 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.54ms    2.21ms  24.39ms   69.07%
    Req/Sec   234.11     30.79   313.00     60.42%
  27990 requests in 30.02s, 10.25MB read
Requests/sec:    932.49
```

---

### Concurrency 10 (c=10, t=4)
* **XDP Throughput**: `21,592.17 RPS` | **Avg Latency**: `327.71 us`
* **vLLM-SR Throughput**: `931.71 RPS` | **Avg Latency**: `8.54 ms`
* **Speedup**: `23.2×` Throughput | `26.0×` Latency

```text
--- [1/2] XDP Route ---
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   327.71us  115.88us   3.58ms   78.64%
    Req/Sec     5.42k   185.32     5.94k    79.24%
  649911 requests in 30.10s, 85.24MB read
Requests/sec:  21592.17

--- [2/2] vLLM-SR Route ---
  4 threads and 10 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     8.54ms    2.37ms  28.86ms   69.98%
    Req/Sec   233.92     33.99   313.00     67.42%
  27968 requests in 30.02s, 10.24MB read
Requests/sec:    931.71
```

---

### Concurrency 16 (c=16, t=4)
* **XDP Throughput**: `25,344.87 RPS` | **Avg Latency**: `595.36 us`
* **vLLM-SR Throughput**: `926.63 RPS` | **Avg Latency**: `17.23 ms`
* **Speedup**: `27.4×` Throughput | `28.9×` Latency

```text
--- [1/2] XDP Route ---
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   595.36us  207.16us  11.70ms   90.50%
    Req/Sec     6.37k   192.33     7.30k    84.75%
  760511 requests in 30.01s, 99.82MB read
Requests/sec:  25344.87

--- [2/2] vLLM-SR Route ---
  4 threads and 16 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    17.23ms    3.97ms  57.85ms   74.90%
    Req/Sec   232.65     33.27   310.00     68.17%
  27819 requests in 30.02s, 10.18MB read
Requests/sec:    926.63
```

---

### Concurrency 32 (c=32, t=4)
* **XDP Throughput**: `25,457.04 RPS` | **Avg Latency**: `1.21 ms`
* **vLLM-SR Throughput**: `924.59 RPS` | **Avg Latency**: `34.58 ms`
* **Speedup**: `27.5×` Throughput | `28.6×` Latency

```text
--- [1/2] XDP Route ---
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     1.21ms  193.01us  12.48ms   68.45%
    Req/Sec     6.40k   175.47     6.97k    82.23%
  766257 requests in 30.10s, 100.57MB read
Requests/sec:  25457.04

--- [2/2] vLLM-SR Route ---
  4 threads and 32 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    34.58ms    7.19ms 114.59ms   81.46%
    Req/Sec   232.10     33.14   320.00     68.17%
  27752 requests in 30.02s, 10.16MB read
Requests/sec:    924.59
```

---

### Concurrency 64 (c=64, t=4)
* **XDP Throughput**: `19,786.41 RPS` | **Avg Latency**: `3.18 ms`
* **vLLM-SR Throughput**: `747.11 RPS` | **Avg Latency**: `85.51 ms`
* **Speedup**: `26.5×` Throughput | `26.9×` Latency

```text
--- [1/2] XDP Route ---
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     3.18ms  476.73us   8.49ms   68.92%
    Req/Sec     4.98k   428.01     9.01k    87.35%
  595564 requests in 30.10s, 78.07MB read
Requests/sec:  19786.41

--- [2/2] vLLM-SR Route ---
  4 threads and 64 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency    85.51ms   16.22ms 284.91ms   81.92%
    Req/Sec   187.61     30.99   330.00     71.00%
  22440 requests in 30.04s, 8.22MB read
Requests/sec:    747.11
```

---

### Concurrency 96 (c=96, t=4)
* **XDP Throughput**: `21,582.43 RPS` | **Avg Latency**: `4.39 ms`
* **vLLM-SR Throughput**: `929.65 RPS` | **Avg Latency**: `103.02 ms`
* **Speedup**: `23.2×` Throughput | `23.5×` Latency

```text
--- [1/2] XDP Route ---
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency     4.39ms  832.33us   8.84ms   63.86%
    Req/Sec     5.44k     0.89k   16.44k    64.36%
  649605 requests in 30.10s, 85.20MB read
Requests/sec:  21582.43

--- [2/2] vLLM-SR Route ---
  4 threads and 96 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   103.02ms   20.00ms 307.54ms   89.00%
    Req/Sec   233.52     37.96   390.00     71.75%
  27921 requests in 30.03s, 10.22MB read
Requests/sec:    929.65
```

---

## Observations: Advantages of XDP

1. **Throughput Scaling**: XDP scales up to **~21,500 – 25,500 RPS** across higher concurrency levels ($c \ge 8$), whereas vllm-sr caps around **~747 – 932 RPS**.
2. **Sub-millisecond Latency**: XDP delivers sub-millisecond average latency at concurrency $\le 16$ ($116\mu\text{s}$ at $c=1$ to $595\mu\text{s}$ at $c=16$) and stays relatively low ($3.18\text{ms}$ at $c=64$, $4.39\text{ms}$ at $c=96$), whereas vllm-sr average latency grows linearly up to **103.02ms**.
3. **Efficiency**: XDP achieves an overall **~17.6× to 27.5× throughput speedup** and **~20.1× to 28.9× latency speedup** compared to application-layer HTTP semantic routing.


<!-- image of latency_comparison -->
<img src="latency_comparison.png" alt="Latency Comparison" width="600"/>