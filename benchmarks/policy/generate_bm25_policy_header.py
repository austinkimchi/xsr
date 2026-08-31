#!/usr/bin/env python3
"""Precompute VSR bm25 2.3 corpus weights for bounded fixed-point eBPF."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import math
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

from generate_keyword_header import (
    decision_keyword_routes,
    keyword_signals,
    load_policy,
    signal_route_name,
)
from vsr_bm25_tokenizer import (
    ENGLISH_STOP_WORDS,
    ascii_words,
    is_ascii_word,
    stem_english,
    tokenize,
)

MAX_RULES = 8
MAX_DOCUMENTS = 16
MAX_DOCUMENT_TOKENS = 16
MAX_CORPUS_TERMS = 128
MAX_TERMS = 2048
SCORE_SCALE = 1_000_000
VOCABULARY_PATH = Path(__file__).with_name("data") / "scowl-american-english-2020.12.07.txt.gz"
VOCABULARY_SHA256 = "9f513f1ceadb6a01c5485b7dbdfd5118dc66cd70b59cae2851292112d4066a32"
ROUTES = {"coding": "XDP_ROUTE_CODING", "math": "XDP_ROUTE_MATH", "qa": "XDP_ROUTE_QA", "writing": "XDP_ROUTE_WRITING"}
OPERATORS = {"OR": "XDP_BM25_OR", "AND": "XDP_BM25_AND", "NOR": "XDP_BM25_NOR"}


def token_hash(token: str) -> int:
    value = 2166136261
    for byte in token.encode("ascii"):
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value


def threshold_micro(value: object) -> int:
    result = int((Decimal(str(value)) * SCORE_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if not 0 <= result <= 0xFFFFFFFF:
        raise ValueError(f"bm25_threshold {value!r} is outside the supported range")
    return result


@lru_cache(maxsize=1)
def vocabulary_by_stem() -> dict[str, frozenset[str]]:
    """Index the pinned SCOWL snapshot once using the VSR Porter2 stemmer."""
    with gzip.open(VOCABULARY_PATH, "rb") as source:
        payload = source.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != VOCABULARY_SHA256:
        raise ValueError(
            f"pinned English vocabulary has SHA-256 {digest}; expected {VOCABULARY_SHA256}"
        )
    index: dict[str, set[str]] = defaultdict(set)
    for line in payload.decode("utf-8").splitlines():
        word = line.strip().lower()
        if word and is_ascii_word(word):
            index[stem_english(word)].add(word)
    return {stem: frozenset(words) for stem, words in index.items()}


def vocabulary_aliases(stem: str, configured_surfaces: set[str]) -> set[str]:
    """Return deterministic vocabulary and ordinary possessive aliases."""
    aliases = set(vocabulary_by_stem().get(stem, ()))
    aliases.update(configured_surfaces)
    aliases.add(stem)
    for surface in tuple(aliases):
        if "'" in surface:
            continue
        possessive = surface + "'s"
        if stem_english(possessive) == stem:
            aliases.add(possessive)
    return aliases


def parse(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    policy = load_policy(path)
    signals = keyword_signals(policy)
    decision_routes, priorities = decision_keyword_routes(policy)
    rules: list[dict[str, object]] = []
    documents: list[dict[str, object]] = []
    term_vectors: dict[int, list[int]] = {}
    hash_tokens: dict[int, str] = {}
    stem_surfaces: dict[str, set[str]] = {}

    for signal in signals:
        if not isinstance(signal, dict) or str(signal.get("method", "")).lower() != "bm25":
            continue
        name = str(signal.get("name", ""))
        route_name = signal_route_name(signal, decision_routes)
        if route_name not in ROUTES:
            raise ValueError(f"{name}: unsupported route {route_name!r}")
        operator = str(signal.get("operator", "OR")).upper()
        if operator not in OPERATORS:
            raise ValueError(f"{name}: operator must be OR, AND, or NOR")
        values = signal.get("keywords")
        if not isinstance(values, list) or not values:
            raise ValueError(f"{name}: keywords must be a non-empty list")
        if len(rules) >= MAX_RULES or len(documents) + len(values) > MAX_DOCUMENTS:
            raise ValueError(f"BM25 supports at most {MAX_RULES} rules and {MAX_DOCUMENTS} keyword documents")

        doc_start = len(documents)
        rule_threshold = threshold_micro(signal.get("bm25_threshold", 0.1))
        corpus = [tokenize(str(value)) for value in values]
        raw_corpus = [ascii_words(str(value)) for value in values]
        if any(not tokens for tokens in corpus):
            raise ValueError(f"{name}: every keyword must contain an ASCII alphanumeric token")
        if any(len(tokens) > MAX_DOCUMENT_TOKENS for tokens in corpus):
            raise ValueError(f"{name}: keyword documents support at most {MAX_DOCUMENT_TOKENS} tokens")
        avgdl = sum(map(len, corpus)) / len(corpus)
        document_frequency = Counter(token for tokens in corpus for token in set(tokens))
        corpus_size = len(corpus)

        for raw_tokens in raw_corpus:
            for surface in raw_tokens:
                stem_surfaces.setdefault(stem_english(surface), set()).add(surface)

        for tokens in corpus:
            doc_id = len(documents)
            documents.append({"rule_id": len(rules), "threshold_micro": rule_threshold})
            frequencies = Counter(tokens)
            for token, tf in frequencies.items():
                hashed = token_hash(token)
                previous = hash_tokens.setdefault(hashed, token)
                if previous != token:
                    raise ValueError(f"BM25 FNV-1a collision between {previous!r} and {token!r}")
                df = document_frequency[token]
                idf = math.log(1.0 + (corpus_size - df + 0.5) / (df + 0.5))
                tf_norm = tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(tokens) / avgdl))
                weight = int(Decimal(str(idf * tf_norm * SCORE_SCALE)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                if not 0 < weight <= 0xFFFFFFFF:
                    raise ValueError(f"BM25 term weight for {token!r} overflows the Q1e6 u32 representation")
                vector = term_vectors.setdefault(hashed, [0] * MAX_DOCUMENTS)
                vector[doc_id] = weight

        rules.append({
            "threshold_micro": rule_threshold,
            "priority": priorities.get(name, int(signal.get("priority", 0))),
            "route": ROUTES[route_name],
            "operator": OPERATORS[operator],
            "document_start": doc_start,
            "document_count": len(values),
            "document_mask": ((1 << len(values)) - 1) << doc_start,
        })

    if len(term_vectors) > MAX_CORPUS_TERMS:
        raise ValueError(
            f"BM25 policy has {len(term_vectors)} corpus terms; maximum is {MAX_CORPUS_TERMS}"
        )
    alias_vectors: dict[int, list[int]] = {}
    for stem, surfaces in stem_surfaces.items():
        stem_hash = token_hash(stem)
        vector = term_vectors[stem_hash]
        aliases = vocabulary_aliases(stem, surfaces)
        for alias in aliases:
            hashed = token_hash(alias)
            previous = hash_tokens.setdefault(hashed, alias)
            if previous != alias:
                raise ValueError(f"BM25 FNV-1a collision between {previous!r} and {alias!r}")
            alias_vectors[hashed] = vector

    stopword_hashes: dict[int, str] = {}
    for stopword in ENGLISH_STOP_WORDS:
        hashed = token_hash(stopword)
        previous = hash_tokens.get(hashed) or stopword_hashes.setdefault(hashed, stopword)
        if previous != stopword:
            raise ValueError(f"BM25 FNV-1a collision between {previous!r} and {stopword!r}")
    terms = [
        {"hash": key, "weights": weights, "stopword": False}
        for key, weights in sorted(alias_vectors.items())
    ]
    terms.extend(
        {"hash": key, "weights": [0] * MAX_DOCUMENTS, "stopword": True}
        for key in sorted(stopword_hashes)
    )
    terms.sort(key=lambda term: int(term["hash"]))
    if len(terms) > MAX_TERMS:
        raise ValueError(f"BM25 policy requires {len(terms)} map terms; maximum is {MAX_TERMS}")
    return rules, documents, terms


def emit(source: Path, rules: list[dict[str, object]], documents: list[dict[str, object]], terms: list[dict[str, object]]) -> str:
    lines = [
        "/* Generated by generate_bm25_policy_header.py. Do not edit. */",
        f"/* Source: {source.as_posix()}; bm25 crate 2.3 defaults, Q1e6 scores. */",
        "#ifndef XDP_BM25_POLICY_GENERATED_H", "#define XDP_BM25_POLICY_GENERATED_H", "",
        f"#define XDP_BM25_GENERATED_RULE_COUNT {len(rules)}",
        f"#define XDP_BM25_GENERATED_DOCUMENT_COUNT {len(documents)}",
        f"#define XDP_BM25_GENERATED_TERM_COUNT {len(terms)}", "",
        "#ifndef __BPF__",
        "static const struct xdp_bm25_policy_config xdp_bm25_generated_config = {",
        f"  .rule_count = {len(rules)}, .document_count = {len(documents)},",
        f"  .thresholds_micro = {{{', '.join(str(document['threshold_micro']) for document in documents)}{', ' if documents else ''}{', '.join('0' for _ in range(MAX_DOCUMENTS - len(documents)))}}},", "};",
        "static const struct xdp_bm25_rule xdp_bm25_generated_rules[] = {",
    ]
    for rule in rules:
        lines.append("  {.threshold_micro = %(threshold_micro)s, .priority = %(priority)s, .route = %(route)s, .operator = %(operator)s, .document_start = %(document_start)s, .document_count = %(document_count)s, .document_mask = %(document_mask)s}," % rule)
    lines.extend(["};", "struct xdp_bm25_generated_term { __u32 hash; struct xdp_bm25_term_weights value; };", "static const struct xdp_bm25_generated_term xdp_bm25_generated_terms[] = {"])
    for term in terms:
        lines.append(
            f"  {{.hash = {term['hash']}U, .value = {{.weights = "
            f"{{{', '.join(map(str, term['weights']))}}}, "
            f".stopword = {int(bool(term['stopword']))}}}}},"
        )
    lines.extend(["};", "#endif", "", "#endif", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("policy", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rules, documents, terms = parse(args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(emit(args.policy, rules, documents, terms))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
