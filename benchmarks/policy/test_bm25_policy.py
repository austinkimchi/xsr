#!/usr/bin/env python3
"""BM25 reference, fixed-point, policy, and module-selection coverage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bm25_reference import fixed_scores, keyword_scores, rule_matches
from generate_bm25_policy_header import MAX_TOKEN_LEN, SCORE_SCALE, parse, threshold_micro
from generate_policy_modules import methods, selection_header


ROOT = Path(__file__).resolve().parents[2]


class Bm25CompatibilityTests(unittest.TestCase):
    def test_repeated_query_terms_accumulate_like_bm25_crate(self) -> None:
        once = keyword_scores("alpha", ["alpha", "beta"])[0]
        repeated = keyword_scores("alpha alpha alpha", ["alpha", "beta"])[0]
        self.assertAlmostEqual(repeated, once * 3, places=6)

    def test_absent_term_and_zero_threshold_do_not_match(self) -> None:
        self.assertFalse(rule_matches("absent", ["alpha"], "OR", 0))

    def test_multiple_keywords_and_operators(self) -> None:
        keywords = ["alpha", "beta"]
        self.assertTrue(rule_matches("alpha", keywords, "OR", 0.1))
        self.assertFalse(rule_matches("alpha", keywords, "AND", 0.1))
        self.assertTrue(rule_matches("alpha beta", keywords, "AND", 0.1))
        self.assertTrue(rule_matches("gamma", keywords, "NOR", 0.1))
        self.assertFalse(rule_matches("beta", keywords, "NOR", 0.1))

    def test_score_boundary_is_inclusive(self) -> None:
        score = keyword_scores("alpha", ["alpha"])[0]
        self.assertTrue(rule_matches("alpha", ["alpha"], "OR", score))
        self.assertFalse(rule_matches("alpha", ["alpha"], "OR", score + 1e-6))

    def test_fixed_point_error_is_bounded_per_query_occurrence(self) -> None:
        query = "alpha alpha beta"
        floating = keyword_scores(query, ["alpha alpha", "beta"])
        fixed = fixed_scores(query, ["alpha alpha", "beta"])
        for expected, actual in zip(floating, fixed):
            self.assertLessEqual(abs(expected - actual / SCORE_SCALE), 3 / SCORE_SCALE)

    def test_policy_precomputes_each_keyword_as_a_document(self) -> None:
        rules, documents, terms = parse(ROOT / "config" / "policy_bm25.yaml")
        self.assertEqual(len(rules), 4)
        self.assertEqual(len(documents), 16)
        self.assertGreater(len(terms), 0)

    def test_threshold_rounding(self) -> None:
        self.assertEqual(threshold_micro("0.1000005"), 100001)

    def test_policy_rejects_tokens_longer_than_runtime_limit(self) -> None:
        source = (ROOT / "config" / "policy_bm25.yaml").read_text()
        with tempfile.TemporaryDirectory() as directory:
            accepted = Path(directory) / "accepted.yaml"
            accepted.write_text(source.replace('"code"', f'"{"a" * MAX_TOKEN_LEN}"', 1))
            parse(accepted)

            rejected = Path(directory) / "rejected.yaml"
            rejected.write_text(source.replace('"code"', f'"{"a" * (MAX_TOKEN_LEN + 1)}"', 1))
            with self.assertRaisesRegex(ValueError, "exceeds the 32-byte runtime limit"):
                parse(rejected)


class ModuleSelectionTests(unittest.TestCase):
    def test_ngram_bm25_and_mixed_selection(self) -> None:
        cases = {
            "policy_ngram.yaml": (1, 0),
            "policy_bm25.yaml": (0, 1),
            "policy_mixed.yaml": (1, 1),
        }
        for filename, enabled in cases.items():
            path = ROOT / "config" / filename
            selected = methods(path)
            header = selection_header(path, selected)
            self.assertIn(f"XDP_KEYWORD_ENABLE_NGRAM {enabled[0]}", header)
            self.assertIn(f"XDP_KEYWORD_ENABLE_BM25 {enabled[1]}", header)


if __name__ == "__main__":
    unittest.main()
