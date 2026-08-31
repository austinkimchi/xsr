# Results

This directory contains only compact, reviewed summaries and provenance.

- `intent-distillation/` records the student-model experiments, independent
  evaluation, deployment parity gate, and recovery diagnostics.
- Performance and correctness runs are local by default. Add a server result
  only after checking its manifest, environment metadata, raw-data scope, and
  absence of host-specific or sensitive values.

The previous workstation performance runs and executed analysis notebook are
kept on `archive/legacy-master` and in the repository backup bundle. Generate a
fresh notebook from reviewed server data with
`benchmarks/routing_wrk/build_analysis_notebook.py`.
