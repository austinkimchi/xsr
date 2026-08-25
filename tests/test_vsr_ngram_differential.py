#!/usr/bin/env python3
"""Differential tests for the VSR `ngrammatic` 0.7 warp-2 contract.

`Corpus::search` delegates to `search_with_warp(..., 2.0, ...)`; Ngram stores
gram multiplicities and calculates `1 - (diff / all)^2`.  `vsr_matches` is a
literal, independent translation of those source operations.  The XSR
reference must make the identical match decision for the bounded ASCII subset.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from jaccard_reference import matches, rule_matches


def vsr_matches(word: str, keyword: str, arity: int, threshold: float) -> bool:
    def grams(value: str) -> Counter[bytes]:
        raw = value.lower().encode("ascii")
        padded = b" " * (arity - 1) + raw + b" " * (arity - 1)
        return Counter(padded[index:index + arity] for index in range(len(padded) - arity + 1))

    left, right = grams(word), grams(keyword)
    same = sum(min(count, right[gram]) for gram, count in left.items())
    # ngrammatic::Ngram::count_allgrams and warp=2 similarity.
    all_grams = sum(left.values()) + sum(right.values()) - same
    score = 0.0 if not all_grams else 1.0 - ((all_grams - same) / all_grams) ** 2
    # Corpus::search considers only candidates sharing an indexed gram.
    return bool(same) and score >= threshold


class VsrDifferentialTests(unittest.TestCase):
    def test_ngrammatic_decisions(self) -> None:
        cases = [
            ("function", "function", 0.8),      # exact/case-insensitive
            ("FUNCTION", "function", 0.8),
            ("functoin", "function", 0.4),       # typo
            ("aaaa", "aaa", 0.7),                # duplicate grams
            ("a", "aa", 0.5),                    # short words
            ("ab", "ac", 0.265),                 # 13/49 is just above threshold
            ("ab", "ac", 0.266),                 # and just below this threshold
            ("xyz", "function", 0.1),            # unrelated
            ("probability", "probability", 0.8),
        ]
        for word, keyword, threshold in cases:
            with self.subTest(word=word, keyword=keyword, threshold=threshold):
                self.assertEqual(matches(word, keyword, 3, threshold, False),
                                 vsr_matches(word, keyword, 3, threshold))

    def test_multiple_keywords_and_operators(self) -> None:
        keywords = ["function", "matrix"]
        self.assertTrue(rule_matches("debug this function", keywords, "OR", 3, 0.8, False))
        self.assertTrue(rule_matches("function matrix", keywords, "AND", 3, 0.8, False))
        self.assertTrue(rule_matches("unrelated words", keywords, "NOR", 3, 0.8, False))
        self.assertFalse(rule_matches("function", keywords, "AND", 3, 0.8, False))


if __name__ == "__main__":
    unittest.main()
