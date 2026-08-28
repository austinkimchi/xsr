"""Bounded ASCII reference for VSR's ngrammatic warp-2 matcher.

This mirrors `Corpus::search`: Pad::Auto on both sides, lowercase input for
the configured case-insensitive subset, multiset gram intersection, and the
default warp of 2.  The XDP program uses the same integer rearrangement of the
score comparison, avoiding floating point in BPF.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Iterable


def threshold_milli(value: object) -> int:
    return int((Decimal(str(value)) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def word_grams(word: str, arity: int, case_sensitive: bool) -> Counter[bytes]:
    if not case_sensitive:
        word = word.lower()
    raw = word.encode("ascii")
    padded = b" " * (arity - 1) + raw + b" " * (arity - 1)
    return Counter(padded[index : index + arity] for index in range(len(padded) - arity + 1))


def words(text: str) -> Iterable[str]:
    # The XDP byte implementation intentionally has the ASCII subset of VSR's
    # Unicode-aware splitter; '-' and '_' remain word characters in both.
    return (word for word in re.split(r"[^A-Za-z0-9_-]+", text) if word)


def similarity_counts(left: Counter[bytes], right: Counter[bytes]) -> tuple[int, int, int]:
    """Return ngrammatic's samegram count, allgram count, and warp-2 numerator."""
    same = sum(min(count, right[gram]) for gram, count in left.items())
    all_grams = sum(left.values()) + sum(right.values()) - same
    numerator = all_grams * all_grams - (all_grams - same) * (all_grams - same)
    return same, all_grams, numerator


def matches(word: str, keyword: str, arity: int, threshold: object, case_sensitive: bool) -> bool:
    left = word_grams(word, arity, case_sensitive)
    right = word_grams(keyword, arity, case_sensitive)
    same, all_grams, numerator = similarity_counts(left, right)
    # Corpus::search only evaluates indexed candidates which share a gram.
    return bool(same and all_grams and numerator * 1000 >= all_grams * all_grams * threshold_milli(threshold))


def rule_matches(text: str, keywords: list[str], operator: str, arity: int,
                 threshold: object, case_sensitive: bool) -> bool:
    matched = {
        keyword for keyword in keywords
        if any(matches(word, keyword, arity, threshold, case_sensitive) for word in words(text))
    }
    operator = operator.upper()
    return (operator == "OR" and bool(matched)) or (operator == "AND" and len(matched) == len(keywords)) or (operator == "NOR" and not matched)
