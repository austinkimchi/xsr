# Results

This directory contains the reported measurements:

- `throughput.csv` and `throughput_trials.csv`: Figure 4 and Tables 7–9.
- `latency_100rps.csv` and `latency_100rps_trials.csv`: Figure 5 and Tables
  10–12.
- `intent_quality.csv`: Table 1.
- `workload_prompt_lengths.csv`: Table 5.
- `correctness.csv`: Table 6.
- `bm25_ablation.csv`: Figure 1 and the forwarding controls.

Latencies are in microseconds unless a column says otherwise. Throughput is in
requests per second. LLMRouter's 100-RPS rows are overload diagnostics rather
than steady-state comparisons.

In Figure 1, XSR's separately measured sub-0.01 ms policy, backend-selection,
and SOCKMAP cost is folded into the displayed remaining-path block, yielding
0.49 ms after rounding.

The saturation measurements use `wrk`; the 100-RPS measurements use the
repository's Python fixed-rate client. Existing N-Gram, Intent, and LLMRouter
rows are unchanged.
