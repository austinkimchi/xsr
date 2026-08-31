#!/usr/bin/env python3
"""BM25 reference, fixed-point, policy, and module-selection coverage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bm25_reference import fixed_scores, keyword_scores, rule_matches
from generate_bm25_policy_header import (
    SCORE_SCALE,
    parse,
    threshold_micro,
    token_hash,
    vocabulary_aliases,
    vocabulary_by_stem,
)
from generate_policy_modules import methods, resolve_profile, selection_header
from vsr_bm25_tokenizer import ENGLISH_STOP_WORDS, stem_english, tokenize, tokenize_query


ROOT = Path(__file__).resolve().parents[2]


class Bm25CompatibilityTests(unittest.TestCase):
    def test_vsr_english_stemming_converges_policy_morphology(self) -> None:
        self.assertEqual(tokenize("function functions"), ["function", "function"])
        self.assertEqual(
            tokenize("implement implemented implementing implementation"),
            ["implement"] * 4,
        )
        self.assertEqual(tokenize("derivative derivatives"), ["deriv", "deriv"])

    def test_vsr_stopwords_are_removed_before_stemming(self) -> None:
        self.assertEqual(tokenize("I am writing the functions"), ["write", "function"])
        self.assertIn("you're", ENGLISH_STOP_WORDS)

    def test_ascii_word_boundaries_keep_decimals_and_contractions(self) -> None:
        self.assertEqual(tokenize("3.14 can't foo_bar"), ["3.14", "can't", "foo_bar"])

    def test_porter2_matches_rust_stemmers_regressions(self) -> None:
        expected = {
            "connections": "connect",
            "relational": "relat",
            "conditional": "condit",
            "triplicate": "triplic",
            "communism": "communism",
            "skies": "sky",
            "proceed": "proceed",
            "playing": "play",
        }
        self.assertEqual({word: stem_english(word) for word in expected}, expected)

    def test_unicode_policy_text_is_rejected_at_the_kernel_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "deunicode normalization"):
            tokenize("functions 🍕")

    def test_unicode_query_codepoints_are_word_boundaries(self) -> None:
        self.assertEqual(tokenize_query("functions—derivatives"), ["function", "deriv"])
        self.assertEqual(tokenize_query("défine"), ["fine"])

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

    def test_streaming_hash_accepts_policy_tokens_longer_than_32_bytes(self) -> None:
        long_token = "streamingtoken" * 4
        source = (ROOT / "config" / "policy_bm25.yaml").read_text()
        source = source.replace('keywords: ["code",', f'keywords: ["{long_token}",', 1)
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "policy.yaml"
            policy.write_text(source)
            _, _, terms = parse(policy)
        self.assertIn(token_hash(long_token), {int(term["hash"]) for term in terms})

    def test_policy_generates_vocabulary_aliases_and_stopwords(self) -> None:
        _, _, terms = parse(ROOT / "config" / "policy_bm25.yaml")
        by_hash = {int(term["hash"]): term for term in terms}
        function = by_hash[token_hash("function")]
        functions = by_hash[token_hash("functions")]
        self.assertEqual(function["weights"], functions["weights"])
        self.assertFalse(function["stopword"])
        self.assertTrue(by_hash[token_hash("the")]["stopword"])
        for alias in ("derive", "equator", "functionality", "writings", "composer's"):
            self.assertIn(token_hash(alias), by_hash)

    def test_aliases_come_from_the_pinned_vocabulary_and_possessive_rule(self) -> None:
        aliases = vocabulary_aliases("compos", {"compose"})
        self.assertIn("composer", vocabulary_by_stem()["compos"])
        self.assertIn("composer's", aliases)
        self.assertNotIn("composeization", aliases)

    def test_threshold_rounding(self) -> None:
        self.assertEqual(threshold_micro("0.1000005"), 100001)

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

    def test_profiles_are_isolated_and_contradictions_fail(self) -> None:
        ngram = ROOT / "config" / "policy_ngram.yaml"
        profile, selected = resolve_profile(ngram, "intent")
        header = selection_header(ngram, profile, selected)
        self.assertIn("XDP_SIGNAL_ENABLE_DISTILL 1", header)
        self.assertIn("XDP_SIGNAL_ENABLE_NGRAM 0", header)
        with self.assertRaisesRegex(ValueError, "contradicts"):
            resolve_profile(ngram, "bm25")

    def test_parity_diagnostics_are_explicit(self) -> None:
        policy = ROOT / "config" / "policy_ngram.yaml"
        self.assertIn("XSR_DISTILL_PARITY_DEBUG 0", selection_header(policy, "intent", set()))
        self.assertIn("XSR_DISTILL_PARITY_DEBUG 1", selection_header(policy, "intent", set(), True))


if __name__ == "__main__":
    unittest.main()
