#!/usr/bin/env python3
"""Unit tests for the ngrammatic-compatible policy preprocessing and scoring."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(POLICY_DIR))

from jaccard_reference import matches, rule_matches, threshold_milli, word_grams
from generate_jaccard_policy_header import casefold_entries, emit, grams, parse, scalar_lower
from generate_unicode_word_header import contains, word_bitmap, word_ranges


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
        self.assertEqual(
            grams("a", 3, False),
            [(ord(" "), ord(" "), ord("a")),
             (ord(" "), ord("a"), ord(" ")),
             (ord("a"), ord(" "), ord(" "))],
        )

    def test_repeated_grams_preserve_multiplicity(self) -> None:
        grams = word_grams("aaaa", 3, False)
        self.assertEqual(sum(grams.values()), 6)
        self.assertEqual(grams["aaa"], 2)
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

    def test_unicode_words_and_case_folding(self) -> None:
        self.assertTrue(matches("CAFÉ", "café", 3, 1.0, False))
        self.assertTrue(matches("функция", "функция", 3, 1.0, False))
        self.assertTrue(matches("函数", "函数", 3, 1.0, False))
        self.assertIn((ord("É"), ord("é")), casefold_entries(["café"]))
        self.assertIn((ord("ẞ"), ord("ß")), casefold_entries(["ß"]))

    def test_unicode_word_boundaries_match_reference(self) -> None:
        ranges = word_ranges()
        bitmap = word_bitmap(ranges)
        for char in ("é", "Ж", "函", "٢"):
            self.assertTrue(contains(ranges, ord(char)))
            self.assertEqual((bitmap[ord(char) >> 6] >> (ord(char) & 63)) & 1, 1)
        for char in ("🙂", "©", "。", "—", "\u00a0"):
            self.assertFalse(contains(ranges, ord(char)))
            self.assertEqual((bitmap[ord(char) >> 6] >> (ord(char) & 63)) & 1, 0)
        self.assertTrue(rule_matches("café🙂", ["café"], "OR", 3, 1.0, False))

    def test_multi_word_phrase_uses_full_text_search(self) -> None:
        self.assertTrue(rule_matches("machine learning", ["machine learning"], "OR", 3, 1.0, False))
        self.assertFalse(rule_matches("machine translation", ["machine learning"], "OR", 3, 0.8, False))

    def test_unicode_phrase_policy_generates_bounded_c_data(self) -> None:
        policy = {
            "routes": [
                {
                    "name": "code_unicode",
                    "route": "coding",
                    "method": "ngram",
                    "operator": "OR",
                    "keywords": ["café", "机器 学习"],
                    "ngram_arity": 3,
                    "ngram_threshold": 0.8,
                    "case_sensitive": False,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "policy.json"
            source.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
            rules, keywords, casefolds = parse(source)
            header = emit(source, rules, keywords, casefolds)

        self.assertEqual(len(keywords), 2)
        self.assertIn((ord("É"), ord("é")), casefolds)
        self.assertIn(f".a = {ord('机')}", header)
        self.assertIn("XDP_JACCARD_GENERATED_CASEFOLD_COUNT", header)

    def test_expanding_case_fold_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "expanding Unicode case folding"):
            grams("İ", 3, False)

    def test_context_sensitive_lowercase_is_rejected(self) -> None:
        self.assertTrue(matches("ΣΟΣ", "σος", 3, 1.0, False))
        self.assertEqual("ΣΟΣ".lower(), "σος")
        self.assertEqual(scalar_lower("ΣΟΣ", "σος"), "σοσ")
        for keyword in ("σος", "σοσ", "ΣΟΣ"):
            with self.subTest(keyword=keyword):
                with self.assertRaisesRegex(ValueError, "context-sensitive Unicode lowercasing"):
                    grams(keyword, 3, False)

        self.assertEqual(grams("σος", 3, True)[0], (ord(" "), ord(" "), ord("σ")))

        policy = {
            "routes": [{
                "name": "greek_sigma",
                "route": "coding",
                "method": "ngram",
                "keywords": ["σος"],
                "case_sensitive": False,
            }]
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "policy.json"
            source.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "context-sensitive Unicode lowercasing"):
                parse(source)


if __name__ == "__main__":
    unittest.main()
