#!/usr/bin/env python3
"""Preprocess a VSR n-gram keyword policy for the XDP Jaccard maps.

The output intentionally contains userspace-only initializers.  xdp_router
loads them into BPF array maps, keeping keyword preprocessing out of XDP.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from collections import Counter

from generate_keyword_header import keyword_signals, load_policy, signal_route_name, decision_keyword_routes

MAX_KEYWORDS = 16
MAX_RULES = 8
MAX_GRAMS = 32
MAX_ARITY = 3
ROUTES = {
    "coding": "XDP_ROUTE_CODING",
    "math": "XDP_ROUTE_MATH",
    "qa": "XDP_ROUTE_QA",
    "writing": "XDP_ROUTE_WRITING",
}
OPERATORS = {"OR": "XDP_JACCARD_OR", "AND": "XDP_JACCARD_AND", "NOR": "XDP_JACCARD_NOR"}


def threshold_milli(value: object) -> int:
    result = int((Decimal(str(value)) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if not 0 <= result <= 1000:
        raise ValueError(f"ngram_threshold {value!r} must be between 0 and 1")
    return result


def scalar_lower(text: str, keyword: str) -> str:
    result: list[str] = []
    for char in text:
        lowered = char.lower()
        if len(lowered) != 1:
            raise ValueError(
                f"keyword {keyword!r} requires expanding Unicode case folding, "
                "which is outside the bounded XDP implementation"
            )
        result.append(lowered)
    return "".join(result)


def normalize(text: str, case_sensitive: bool) -> str:
    if case_sensitive:
        return text
    lowered = text.lower()
    scalar_lower(text, text)
    uppercase = text.upper()
    if uppercase.lower() != scalar_lower(uppercase, text):
        raise ValueError(
            f"keyword {text!r} requires context-sensitive Unicode lowercasing, "
            "which the scalar XDP case-fold map cannot reproduce"
        )
    return lowered


def gram_counts(keyword: str, arity: int, case_sensitive: bool) -> tuple[list[tuple[int, int, int]], list[int], int]:
    normalized = normalize(keyword, case_sensitive)
    padded = " " * (arity - 1) + normalized + " " * (arity - 1)
    all_grams = [
        tuple(ord(char) for char in padded[index : index + arity])
        for index in range(len(padded) - arity + 1)
    ]
    if len(all_grams) > MAX_GRAMS:
        raise ValueError(
            f"keyword {keyword!r} produces {len(all_grams)} trigrams; max is {MAX_GRAMS} "
            "for the bounded ngrammatic-compatible XDP matcher"
        )
    counts = Counter(all_grams)
    result: list[int] = []
    multiplicities: list[int] = []
    for value in all_grams:
        if value not in result:
            result.append(value)
            multiplicities.append(counts[value])
    if len(result) > MAX_GRAMS:
        raise ValueError(f"keyword {keyword!r} produces {len(result)} unique grams; max is {MAX_GRAMS}")
    return result, multiplicities, len(all_grams)


def grams(keyword: str, arity: int, case_sensitive: bool) -> list[tuple[int, int, int]]:
    """Compatibility helper returning the distinct packed grams in source order."""
    return gram_counts(keyword, arity, case_sensitive)[0]


def casefold_entries(texts: list[str]) -> list[tuple[int, int]]:
    targets = {char for text in texts for char in text.lower()}
    entries: dict[int, int] = {}
    # Reverse Python's one-to-one lowercase mapping for every Unicode scalar.
    # Deriving variants from upper()/title() misses characters such as ẞ,
    # whose uppercase form expands even though its lowercase form does not.
    for codepoint in range(sys.maxunicode + 1):
        char = chr(codepoint)
        lower = char.lower()
        if len(lower) == 1 and lower in targets and char != lower:
            entries[codepoint] = ord(lower)
    if len(entries) > 128:
        raise ValueError("Unicode case-fold policy requires more than 128 bounded mappings")
    return sorted(entries.items())


def parse(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], list[tuple[int, int]]]:
    policy = load_policy(path)
    signals = keyword_signals(policy)
    decision_routes, priorities = decision_keyword_routes(policy)
    rules: list[dict[str, object]] = []
    keywords: list[dict[str, object]] = []
    insensitive_texts: list[str] = []
    policy_case_sensitive: bool | None = None
    for signal in signals:
        if not isinstance(signal, dict) or str(signal.get("method", "")).lower() != "ngram":
            raise ValueError("XDP Jaccard policies must contain only method: ngram keyword signals")
        name = str(signal.get("name", ""))
        route_name = signal_route_name(signal, decision_routes)
        if route_name not in ROUTES:
            raise ValueError(f"{name}: route must be coding, math, qa, or writing")
        operator = str(signal.get("operator", "OR")).upper()
        if operator not in OPERATORS:
            raise ValueError(f"{name}: operator must be OR, AND, or NOR")
        arity = int(signal.get("ngram_arity", 3))
        if arity != MAX_ARITY:
            raise ValueError(f"{name}: XDP's verifier-bounded implementation currently supports ngram_arity: {MAX_ARITY}")
        values = signal.get("keywords")
        if not isinstance(values, list) or not values:
            raise ValueError(f"{name}: keywords must be a non-empty list")
        if len(rules) >= MAX_RULES:
            raise ValueError(f"at most {MAX_RULES} keyword rules are supported")
        case_sensitive = bool(signal.get("case_sensitive", False))
        if policy_case_sensitive is None:
            policy_case_sensitive = case_sensitive
        elif policy_case_sensitive != case_sensitive:
            raise ValueError("XDP requires the same case_sensitive value for every ngram rule")
        rule_id = len(rules)
        rules.append({
            "threshold_milli": threshold_milli(signal.get("ngram_threshold", 0.4)),
            "priority": priorities.get(name, int(signal.get("priority", 0))),
            "route": ROUTES[route_name], "operator": OPERATORS[operator],
            "arity": arity, "case_sensitive": int(case_sensitive),
            "keyword_count": len(values),
        })
        for value in values:
            if len(keywords) >= MAX_KEYWORDS:
                raise ValueError(f"at most {MAX_KEYWORDS} keywords are supported")
            text = str(value)
            if not text:
                raise ValueError(f"{name}: empty keywords are not supported")
            gram_values, counts, total = gram_counts(text, arity, case_sensitive)
            keywords.append({"rule_id": rule_id, "grams": gram_values, "counts": counts, "total_grams": total})
            if not case_sensitive:
                insensitive_texts.append(text)
    return rules, keywords, casefold_entries(insensitive_texts)


def emit(source: Path, rules: list[dict[str, object]], keywords: list[dict[str, object]],
         casefolds: list[tuple[int, int]]) -> str:
    lines = [
        "/* Generated by benchmarks/policy/generate_jaccard_policy_header.py. Do not edit. */",
        f"/* Source: {source.as_posix()}; Pad::Auto-compatible Unicode preprocessing. */",
        "#ifndef XDP_JACCARD_POLICY_GENERATED_H", "#define XDP_JACCARD_POLICY_GENERATED_H", "",
        f"#define XDP_JACCARD_GENERATED_RULE_COUNT {len(rules)}",
        f"#define XDP_JACCARD_GENERATED_KEYWORD_COUNT {len(keywords)}", "",
        f"#define XDP_JACCARD_GENERATED_CASEFOLD_COUNT {len(casefolds)}", "",
        "#ifndef __BPF__",
        "static const struct xdp_jaccard_policy_config xdp_jaccard_generated_config = {",
        f"  .keyword_count = {len(keywords)}, .rule_count = {len(rules)}, "
        f".case_sensitive = {rules[0]['case_sensitive'] if rules else 0},", "};",
        "static const struct xdp_jaccard_rule xdp_jaccard_generated_rules[] = {",
    ]
    for rule in rules:
        lines.append("  {.threshold_milli = %(threshold_milli)s, .priority = %(priority)s, .route = %(route)s, .operator = %(operator)s, .arity = %(arity)s, .case_sensitive = %(case_sensitive)s, .keyword_count = %(keyword_count)s}," % rule)
    lines.extend(["};", "static const struct xdp_jaccard_keyword xdp_jaccard_generated_keywords[] = {"])
    for keyword in keywords:
        values = list(keyword["grams"])
        counts = list(keyword["counts"])
        values.extend([(0, 0, 0)] * (MAX_GRAMS - len(values)))
        counts.extend([0] * (MAX_GRAMS - len(counts)))
        lines.append(
            f"  {{.count = {len(keyword['grams'])}, .total_grams = {keyword['total_grams']}, "
            f".grams = {{{', '.join(f'{{.a = {a}, .b = {b}, .c = {c}}}' for a, b, c in values)}}}, "
            f".gram_counts = {{{', '.join(map(str, counts))}}}, "
            f".rule_id = {keyword['rule_id']}}},"
        )
    lines.extend(["};", "static const struct xdp_jaccard_casefold xdp_jaccard_generated_casefolds[] = {"])
    lines.extend(f"  {{.from = {source_cp}, .to = {target_cp}}}," for source_cp, target_cp in casefolds)
    if not casefolds:
        lines.append("  {.from = 0, .to = 0},")
    lines.extend(["};", "#endif", "", "#endif", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("policy", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rules, keywords, casefolds = parse(args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(emit(args.policy, rules, keywords, casefolds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
