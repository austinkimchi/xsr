from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "vsr_profile_components.py"
SPEC = importlib.util.spec_from_file_location("vsr_profile_components", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def snapshot(count: int, duration_base: int) -> str:
    lines = ["# HELP unrelated ignored", "unrelated_metric 9"]
    for index, stage in enumerate(MODULE.STAGES, start=1):
        lines.append(
            f'vsr_component_profile_events_total{{stage="{stage}"}} {count}'
        )
        lines.append(
            "vsr_component_profile_duration_nanoseconds_total"
            f'{{stage="{stage}"}} {duration_base * index}'
        )
    return "\n".join(lines) + "\n"


class VSRProfileComponentsTest(unittest.TestCase):
    def test_subtracts_snapshots_and_sums_direct_parse_timers(self) -> None:
        result = MODULE.summarize_snapshots(snapshot(10, 100), snapshot(15, 1100), 5)

        self.assertEqual(result["completed_requests"], 5)
        self.assertEqual(result["stages"]["bm25_native"]["total_ns"], 3000)
        self.assertEqual(result["figure_components"]["request_parsing"]["total_ns"], 3000)
        self.assertEqual(result["figure_components"]["request_parsing"]["mean_us"], 0.6)
        self.assertTrue(result["request_body_total_is_inclusive"])

    def test_rejects_mismatched_stage_counts(self) -> None:
        after = snapshot(15, 1100).replace(
            'events_total{stage="bm25_native"} 15',
            'events_total{stage="bm25_native"} 14',
        )
        with self.assertRaisesRegex(RuntimeError, "event counts differ"):
            MODULE.summarize_snapshots(snapshot(10, 100), after)

    def test_rejects_counter_reset_between_snapshots(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "counters decreased"):
            MODULE.summarize_snapshots(snapshot(10, 1000), snapshot(5, 100))

    def test_rejects_missing_profile_metrics(self) -> None:
        with self.assertRaisesRegex(ValueError, "is missing"):
            MODULE.parse_snapshot("unrelated_metric 1\n")


if __name__ == "__main__":
    unittest.main()
