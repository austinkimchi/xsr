#!/usr/bin/env python3
"""Regression coverage for the mixed routing-correctness corpus."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = Path(__file__).with_name("benchmark.py")
SPEC = importlib.util.spec_from_file_location("routing_correctness_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def observation(
    case_id: str,
    source: str,
    source_index: int,
    prompt: str,
    expected: str,
    route: str,
    reference_kind: str,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "source": source,
        "source_index": source_index,
        "prompt": prompt,
        "expected_route": expected,
        "route": route,
        "reference_kind": reference_kind,
        "reference_route_match": route == expected,
    }


def mode_result(mode: str, observations: list[dict[str, object]]) -> dict[str, object]:
    return {
        "mode": mode,
        "status": "ok",
        "requests": len(observations),
        "expected_requests": len(observations),
        "results": observations,
    }


class RouterArenaAdapterTests(unittest.TestCase):
    def test_capitalized_fields_context_question_and_options(self) -> None:
        prompt = benchmark.routerarena_prompt_from_row(
            {
                "Context": "A short context.",
                "Question": "Which answer?",
                "Options": ["First", "Second", "Third"],
                "Answer": "Second",
            }
        )
        self.assertEqual(
            prompt,
            "A short context.\n\nWhich answer?\n\nA. First\nB. Second\nC. Third",
        )
        self.assertNotIn("Answer", prompt)

    def test_quotes_unicode_and_json_encoding_are_preserved(self) -> None:
        prompt = benchmark.routerarena_prompt_from_row(
            {"Context": "Él dijo \"hola\".", "Question": "为什么?", "Options": ["✓", "否"]}
        )
        self.assertIn('"hola"', prompt)
        self.assertIn("为什么", prompt)
        decoded = json.loads(benchmark.chat_body(prompt))
        self.assertEqual(decoded["messages"][0]["content"], prompt)

    def test_long_prompt_keeps_first_and_last_5000_characters(self) -> None:
        question = "a" * 5001 + "b" * 5001
        prompt = benchmark.routerarena_prompt_from_row({"Question": question})
        self.assertEqual(len(prompt), 10001)
        self.assertEqual(prompt[:5000], "a" * 5000)
        self.assertEqual(prompt[5000], "…")
        self.assertEqual(prompt[-5000:], "b" * 5000)

    def test_missing_question_uses_other_available_components(self) -> None:
        self.assertEqual(
            benchmark.routerarena_prompt_from_row({"Question": "", "Options": ["one", "two"]}),
            "A. one\nB. two",
        )
        self.assertIsNone(benchmark.routerarena_prompt_from_row({"Question": "", "Context": "", "Options": []}))

    def test_global_index_case_id_and_metadata_are_stable(self) -> None:
        rows = [
            {
                "Global Index": 42,
                "Context": "",
                "Question": "Write a Python function",
                "Options": [],
                "Domain": "Computer science",
                "Category": "Programming",
                "Dataset name": "fixture",
                "Difficulty": "easy",
            }
        ]
        args = argparse.Namespace(routerarena_split="full")
        routes = [
            {
                "name": "coding",
                "method": "ngram",
                "keywords": ["python function"],
                "operator": "OR",
                "ngram_arity": 3,
                "ngram_threshold": 0.4,
            }
        ]
        meta = {
            "source": "RouteWorks/RouterArena",
            "config": "default",
            "split": "full",
            "scanned_rows": 1,
        }
        with mock.patch.object(benchmark, "load_routerarena_rows", return_value=(rows, meta)):
            cases, _ = benchmark.load_routerarena_cases(args, routes, False)
        self.assertEqual(cases[0].case_id, "routerarena:full:42")
        self.assertEqual(cases[0].reference_kind, "policy-oracle")
        self.assertEqual(cases[0].source_metadata["Difficulty"], "easy")

    def test_duplicate_prompts_are_counted_but_not_removed(self) -> None:
        cases = [
            benchmark.Case("same", "others", None, 0, "speed:0", "speed-bench", "dataset-category"),
            benchmark.Case(" same ", "others", None, 0, "arena:0", "routerarena", "policy-oracle"),
            benchmark.Case("same", "others", None, 1, "arena:1", "routerarena", "policy-oracle"),
        ]
        stats = benchmark.corpus_duplicate_stats(cases)
        self.assertEqual(stats["corpus_entries"], 3)
        self.assertEqual(stats["unique_prompts"], 1)
        self.assertEqual(stats["cross_source_duplicate_groups"], 1)
        self.assertEqual(stats["duplicate_entries_within_sources"], 1)


class RoutingCorrectnessComparisonTests(unittest.TestCase):
    def test_bm25_reference_drives_final_route_priority(self) -> None:
        routes = [
            {"name": "coding", "priority": 100, "method": "bm25", "operator": "OR", "keywords": ["code"], "bm25_threshold": 0.1},
            {"name": "math", "priority": 90, "method": "bm25", "operator": "OR", "keywords": ["solve"], "bm25_threshold": 0.1},
        ]
        self.assertEqual(benchmark.expected_route("solve then code", routes, False)[0], "coding")
        self.assertEqual(benchmark.expected_route("nothing relevant", routes, False)[0], "others")

    def test_mixed_methods_use_the_shared_policy_order(self) -> None:
        routes = [
            {"name": "coding", "priority": 100, "method": "ngram", "operator": "OR", "keywords": ["code"], "ngram_arity": 3, "ngram_threshold": 0.8},
            {"name": "math", "priority": 90, "method": "bm25", "operator": "OR", "keywords": ["solve"], "bm25_threshold": 0.1},
        ]
        self.assertEqual(benchmark.expected_route("solve", routes, False)[0], "math")

    def test_source_index_collisions_use_case_id_and_report_per_source(self) -> None:
        xdp_observations = [
            observation("speed:0", "speed-bench", 0, "same", "coding", "coding", "dataset-category"),
            observation("arena:0", "routerarena", 0, "same", "math", "math", "policy-oracle"),
        ]
        comparison = benchmark.xsr_vsr_routing_agreement(
            [mode_result("xdp", xdp_observations), mode_result("vllm-sr", list(xdp_observations))]
        )
        self.assertEqual(comparison["status"], "ok")
        self.assertEqual(comparison["total"], 2)
        self.assertEqual(comparison["per_source"]["speed-bench"]["total"], 1)
        self.assertEqual(comparison["per_source"]["routerarena"]["total"], 1)

    def test_route_permutation_is_not_treated_as_agreement(self) -> None:
        xdp = mode_result(
            "xdp",
            [
                observation("speed:10", "speed-bench", 10, "first", "coding", "coding", "dataset-category"),
                observation("speed:11", "speed-bench", 11, "second", "math", "math", "dataset-category"),
            ],
        )
        vllm = mode_result(
            "vllm-sr",
            [
                observation("speed:10", "speed-bench", 10, "first", "coding", "math", "dataset-category"),
                observation("speed:11", "speed-bench", 11, "second", "math", "coding", "dataset-category"),
            ],
        )
        comparison = benchmark.xsr_vsr_routing_agreement([xdp, vllm])
        self.assertEqual(comparison["status"], "ok")
        self.assertEqual(comparison["agreement_count"], 0)
        self.assertEqual(len(comparison["mismatches"]), 2)
        self.assertEqual(comparison["request_comparisons"][0]["case_id"], "speed:10")

    def test_mixed_reference_kinds_and_routerarena_breakdown(self) -> None:
        results = [
            benchmark.Result(
                "speed", "coding", 200, 1.0, "coding", None, 0,
                "speed:0", "speed-bench", "dataset-category", {"category": "coding"},
            ),
            benchmark.Result(
                "arena", "math", 200, 1.0, "coding", None, 0,
                "arena:0", "routerarena", "policy-oracle", {"Domain": "STEM", "Difficulty": "hard"},
            ),
        ]
        summary = benchmark.summarize("xdp", results, 1.0, None, None)
        self.assertIsNone(summary["route_agreement"])
        self.assertEqual(summary["reference_agreement"]["dataset-category"]["agreement_count"], 1)
        self.assertEqual(summary["reference_agreement"]["policy-oracle"]["agreement_count"], 0)
        self.assertEqual(summary["route_counts_by_source"]["speed-bench"]["coding"], 1)
        self.assertEqual(summary["route_counts_by_source"]["routerarena"]["coding"], 1)
        self.assertEqual(summary["routerarena_breakdown"]["domain"]["STEM"]["total"], 1)
        self.assertEqual(summary["routerarena_breakdown"]["difficulty"]["hard"]["agreement_count"], 0)

    def test_mixed_report_keeps_reference_labels_separate(self) -> None:
        results = [
            benchmark.Result(
                "speed", "coding", 200, 1.0, "coding", None, 0,
                "speed:0", "speed-bench", "dataset-category", {"category": "coding"},
            ),
            benchmark.Result(
                "arena", "math", 200, 1.0, "math", None, 0,
                "arena:0", "routerarena", "policy-oracle", {"Domain": "STEM", "Difficulty": "easy"},
            ),
        ]
        mode_results = [
            benchmark.summarize("xdp", results, 1.0, None, None),
            benchmark.summarize("vllm-sr", results, 1.0, None, None),
        ]
        selected = {**{route: 0 for route in benchmark.ROUTES}, "duplicate_prompt": 0, "missing_prompt": 0, "embedded_quote": 0}
        report = {
            "concurrency": 1,
            "dataset": {
                "sent_cases": 2,
                "duplicates": benchmark.corpus_duplicate_stats(
                    [
                        benchmark.Case("speed", "coding", None, 0, "speed:0", "speed-bench", "dataset-category"),
                        benchmark.Case("arena", "math", None, 0, "arena:0", "routerarena", "policy-oracle"),
                    ]
                ),
                "sources": [
                    {"source": "nvidia/SPEED-Bench", "config": "qualitative", "split": "test", "scanned_rows": 1, "revision": "unversioned", "fingerprint": "fixture", "prompt_format": "speed-v1", "selected_counts": {**selected, "coding": 1}},
                    {"source": "RouteWorks/RouterArena", "config": "default", "split": "full", "scanned_rows": 1, "revision": "pinned", "fingerprint": "fixture", "prompt_format": benchmark.ROUTERARENA_PROMPT_FORMAT, "selected_counts": {**selected, "math": 1}},
                ],
            },
            "policy": {"case_sensitive": False, "keyword_count": 16},
            "results": mode_results,
            "comparison": benchmark.comparison(mode_results),
            "xsr_vsr_routing_agreement": benchmark.xsr_vsr_routing_agreement(mode_results),
        }
        with tempfile.TemporaryDirectory() as directory:
            benchmark.write_reports(report, Path(directory), "mixed.md", True)
            markdown = (Path(directory) / "mixed.md").read_text()
            payload = json.loads((Path(directory) / "mixed.json").read_text())
        self.assertIn("SPEED dataset-label agreement", markdown)
        self.assertIn("RouterArena policy-oracle agreement", markdown)
        self.assertIn("Route Distribution by Source", markdown)
        self.assertIsNone(payload["results"][0]["route_agreement"])


if __name__ == "__main__":
    unittest.main()
