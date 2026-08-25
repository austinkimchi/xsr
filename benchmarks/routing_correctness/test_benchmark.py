#!/usr/bin/env python3
"""Regression coverage for request-for-request routing agreement."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = Path(__file__).with_name("benchmark.py")
SPEC = importlib.util.spec_from_file_location("routing_correctness_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def mode_result(mode: str, observations: list[dict[str, object]]) -> dict[str, object]:
    return {
        "mode": mode,
        "status": "ok",
        "requests": len(observations),
        "expected_requests": len(observations),
        "results": observations,
    }


class RoutingCorrectnessComparisonTests(unittest.TestCase):
    def test_route_permutation_is_not_treated_as_agreement(self) -> None:
        xdp = mode_result(
            "xdp",
            [
                {"source_index": 10, "prompt": "first", "expected_route": "coding", "route": "coding", "reference_route_match": True},
                {"source_index": 11, "prompt": "second", "expected_route": "math", "route": "math", "reference_route_match": True},
            ],
        )
        # The counts still contain one coding and one math route, but each
        # route is assigned to the wrong request.
        vllm = mode_result(
            "vllm-sr",
            [
                {"source_index": 10, "prompt": "first", "expected_route": "coding", "route": "math", "reference_route_match": False},
                {"source_index": 11, "prompt": "second", "expected_route": "math", "route": "coding", "reference_route_match": False},
            ],
        )

        comparison = benchmark.xsr_vsr_routing_agreement([xdp, vllm])

        self.assertEqual(comparison["status"], "ok")
        self.assertEqual(comparison["agreement_count"], 0)
        self.assertEqual(len(comparison["mismatches"]), 2)
        self.assertEqual(comparison["request_comparisons"][0]["source_index"], 10)


if __name__ == "__main__":
    unittest.main()
