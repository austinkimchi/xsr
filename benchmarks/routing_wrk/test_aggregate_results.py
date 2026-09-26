#!/usr/bin/env python3
from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from aggregate_results import aggregate, load_records


def record(trial: int, throughput: float | None) -> dict[str, object]:
    data: dict[str, object] = {"mode": "saturation", "configuration": "concurrency-001", "system": "XSR (SK_SKB/SOCKMAP)", "topology": "host-veth", "trial": trial, "raw_output": f"trial-{trial}.txt", "valid": throughput is not None}
    if throughput is None:
        data["failure_reasons"] = ["timeout errors=1"]
    else:
        data["metrics"] = {name: throughput for name in ("throughput_rps", "average_latency_us", "p50_latency_us", "p95_latency_us", "p99_latency_us")}
    return data


class AggregateResultsTest(unittest.TestCase):
    def test_failed_trials_are_reported_but_excluded_from_statistics(self) -> None:
        result = aggregate([record(1, 10.0), record(2, 20.0), record(3, None)])[0]
        self.assertEqual(result["valid_trial_count"], 2)
        self.assertEqual(result["failed_trial_count"], 1)
        summary = result["metrics"]["throughput_rps"]
        self.assertEqual(summary["mean"], 15.0)
        self.assertAlmostEqual(summary["stdev"], 7.0710678118654755)
        self.assertEqual(summary["median"], 15.0)
        self.assertEqual(summary["minimum"], 10.0)
        self.assertEqual(summary["maximum"], 20.0)

    def test_python_fixed_rate_summary_is_loaded_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            output = run_dir / "raw/fixed-rate/rate-100_concurrency-4/trial-01/xsr"
            output.mkdir(parents=True)
            (output / "summary.json").write_text(json.dumps({
                "system": "XSR (SK_SKB/SOCKMAP)",
                "requested_rps": 100,
                "achieved_rps": 100.0,
                "scheduled_requests": 4000,
                "completed_requests": 4000,
                "http_errors": 0,
                "connection_errors": 0,
                "timeout_errors": 0,
                "other_errors": 0,
                "requests_scheduled_while_worker_busy": 0,
                "max_absolute_scheduling_error_us": 500.0,
                "actual_latency_us": {
                    "mean": 450.0, "p50": 400.0, "p95": 700.0, "p99": 900.0,
                },
            }), encoding="utf-8")
            records = load_records(run_dir)
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["valid"])
        self.assertEqual(records[0]["metrics"]["average_latency_us"], 450.0)


if __name__ == "__main__":
    unittest.main()
