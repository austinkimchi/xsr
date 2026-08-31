"""Focused tests for hardened benchmark-analysis helpers."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from analysis_utils import (
    REQUIRED_SYSTEMS, diagnostic_rows, exclusion_reasons, flatten_summary, paired_ratios,
    parse_configuration, parse_wrk_output, paper_valid_configurations,
)


class AnalysisUtilsTest(unittest.TestCase):
    def test_configuration_parsing(self):
        self.assertEqual(parse_configuration("concurrency-256"), {"concurrency": 256, "offered_rate_rps": None})
        self.assertEqual(parse_configuration("rate-900_concurrency-16"), {"concurrency": 16, "offered_rate_rps": 900})
        with self.assertRaises(ValueError):
            parse_configuration("concurrency=256")

    def test_summary_flattening_converts_latency_once(self):
        summary = {"results": [{"mode": "saturation", "configuration": "concurrency-1", "system": "XSR (SK_SKB/SOCKMAP)", "topology": "host-veth", "valid_trial_count": 2, "failed_trial_count": 0, "metrics": {"average_latency_us": {"mean": 1500, "stdev": 10, "median": 1500, "minimum": 1490, "maximum": 1510, "ci95": 14}, "throughput_rps": {"mean": 20, "stdev": 1, "median": 20, "minimum": 19, "maximum": 21, "ci95": 1.4}}}]}
        rows = flatten_summary(summary, "run")
        latency = next(row for row in rows if row["metric"] == "average_latency_us")
        self.assertEqual(latency["mean"], 1.5)
        self.assertEqual(next(row for row in rows if row["metric"] == "throughput_rps")["mean"], 20.0)

    def test_invalid_trials_are_excluded_from_paired_ratios(self):
        records = [
            {"configuration": "concurrency-1", "concurrency": 1, "offered_rate_rps": None, "trial": 1, "system": "X", "valid": True, "throughput_rps": 10},
            {"configuration": "concurrency-1", "concurrency": 1, "offered_rate_rps": None, "trial": 1, "system": "Y", "valid": True, "throughput_rps": 5},
            {"configuration": "concurrency-1", "concurrency": 1, "offered_rate_rps": None, "trial": 2, "system": "X", "valid": True, "throughput_rps": 20},
            {"configuration": "concurrency-1", "concurrency": 1, "offered_rate_rps": None, "trial": 2, "system": "Y", "valid": False},
        ]
        ratios = paired_ratios(records, "X", "Y", "throughput_rps")
        self.assertEqual([(row["trial"], row["ratio"]) for row in ratios], [(1, 2.0)])

    def test_exclusions_keep_512_out_of_headline_domain(self):
        rows = []
        for concurrency in (256, 512):
            for system in REQUIRED_SYSTEMS:
                rows.append({"configuration": f"concurrency-{concurrency}", "concurrency": concurrency, "metric": "throughput_rps", "system": system, "valid_trial_count": 5, "failed_trial_count": 0})
        exclusions = exclusion_reasons(rows, 5)
        self.assertIn("concurrency-512", exclusions)
        self.assertEqual(paper_valid_configurations(rows, 5), {"concurrency-256"})

    def test_missing_requested_metric_excludes_a_configuration(self):
        rows = []
        for system in REQUIRED_SYSTEMS:
            rows.append({"configuration": "concurrency-1", "concurrency": 1, "metric": "throughput_rps", "system": system, "valid_trial_count": 5, "failed_trial_count": 0})
        exclusions = exclusion_reasons(rows, 5, required_metrics=("throughput_rps", "average_latency_us"))
        self.assertIn("concurrency-1", exclusions)
        self.assertIn("missing required metric", "; ".join(exclusions["concurrency-1"]))

    def test_diagnostic_parser_marks_raw_values_separately(self):
        parsed = parse_wrk_output("  Latency 960.29ms 146ms 1.96s\nSocket errors: connect 0, read 0, write 0, timeout 7\nRequests/sec: 526.80\n[Lua] latency percentiles: p50=953399.00us p95=1043322.00us p99=1758427.00us\n")
        self.assertEqual(parsed["timeout_count"], 7)
        self.assertAlmostEqual(parsed["maximum_latency_ms"], 1960.0)
        self.assertAlmostEqual(parsed["throughput_rps"], 526.8)

    def test_diagnostic_rows_fall_back_from_unreadable_archived_path(self):
        with TemporaryDirectory() as directory:
            result_path = Path(directory) / "result.json"
            fallback = result_path.with_name("wrk.txt")
            fallback.write_text("Requests/sec: 500.25\n", encoding="utf-8")
            archived = Path("/root/archived/wrk.txt")
            original_is_file = Path.is_file

            def guarded_is_file(path):
                if path == archived:
                    raise PermissionError(path)
                return original_is_file(path)

            record = {
                "mode": "saturation", "concurrency": 512,
                "system": "Direct backend", "raw_output": str(archived),
                "result_path": str(result_path), "failure_reasons": [],
            }
            with patch.object(Path, "is_file", guarded_is_file):
                rows = diagnostic_rows(Path(directory), [record], 512)

            self.assertEqual(rows[0]["raw_file_path"], str(fallback))
            self.assertAlmostEqual(rows[0]["throughput_rps"], 500.25)


if __name__ == "__main__":
    unittest.main()
