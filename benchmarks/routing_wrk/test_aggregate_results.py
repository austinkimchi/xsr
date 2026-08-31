#!/usr/bin/env python3
from __future__ import annotations

import unittest

from aggregate_results import aggregate


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


if __name__ == "__main__":
    unittest.main()
