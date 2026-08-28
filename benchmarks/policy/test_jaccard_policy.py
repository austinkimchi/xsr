#!/usr/bin/env python3
"""Unit tests for the ngrammatic-compatible policy preprocessing and scoring."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from jaccard_reference import matches, rule_matches, threshold_milli, word_grams
from generate_jaccard_policy_header import grams


class JaccardKeywordTests(unittest.TestCase):
    def test_exact_keyword(self) -> None:
        self.assertTrue(matches("function", "function", 3, 1.0, False))

    def test_minor_typo_and_unrelated_word(self) -> None:
        self.assertTrue(matches("functoin", "function", 3, 0.4, False))
        self.assertFalse(matches("banana", "function", 3, 0.4, False))

    def test_case_and_short_strings_use_auto_padding(self) -> None:
        self.assertTrue(matches("ASAP", "asap", 3, 1.0, False))
        self.assertTrue(matches("a", "a", 3, 1.0, False))
        self.assertFalse(matches("a", "b", 3, 0.001, False))

    def test_preprocessor_uses_direct_packed_auto_padded_grams(self) -> None:
        self.assertEqual(grams("a", 3, False), [0x202061, 0x206120, 0x612020])

    def test_repeated_grams_preserve_multiplicity(self) -> None:
        grams = word_grams("aaaa", 3, False)
        self.assertEqual(sum(grams.values()), 6)
        self.assertEqual(grams[b"aaa"], 2)
        self.assertNotEqual(grams, word_grams("aaaaa", 3, False))

    def test_inclusive_boundary_integer_comparison(self) -> None:
        self.assertEqual(threshold_milli("0.4"), 400)
        # warp=2 score for same=2, all=5 is (25 - 9) / 25 = 0.640.
        self.assertTrue((25 - 9) * 1000 >= 25 * threshold_milli("0.64"))
        self.assertFalse((25 - 9) * 1000 >= 25 * threshold_milli("0.641"))

    def test_or_and_nor_and_word_extraction(self) -> None:
        self.assertTrue(rule_matches("debug this function", ["debug", "code"], "OR", 3, 1.0, False))
        self.assertTrue(rule_matches("debug this function", ["debug", "function"], "AND", 3, 1.0, False))
        self.assertTrue(rule_matches("friendly prose", ["debug", "function"], "NOR", 3, 1.0, False))
        self.assertTrue(matches("foo-bar", "foo-bar", 3, 1.0, False))


if __name__ == "__main__":
    unittest.main()
