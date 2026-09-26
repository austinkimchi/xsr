#!/usr/bin/env python3
"""Generate build-local native tables for the component ablation harness."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "benchmarks" / "policy"
sys.path.insert(0, str(POLICY))

from generate_bm25_policy_header import (  # noqa: E402
    ENGLISH_STOP_WORDS,
    SCORE_SCALE,
    parse as parse_production_bm25,
    threshold_fixed,
    token_hash,
    vocabulary_aliases,
)
from generate_keyword_header import (  # noqa: E402
    decision_keyword_routes,
    keyword_signals,
    load_policy,
    signal_route_name,
)
from vsr_bm25_tokenizer import ascii_words, stem_english, tokenize  # noqa: E402


ROUTE_IDS = {"coding": 0, "others": 1, "math": 2, "qa": 3, "writing": 4}
OPERATORS = {"OR": 0, "AND": 1, "NOR": 2}
MAX_DOCUMENTS = 16


def c_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def ngram_tables(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    policy = load_policy(path)
    routes, priorities = decision_keyword_routes(policy)
    rules: list[dict[str, object]] = []
    keywords: list[dict[str, object]] = []
    for signal in keyword_signals(policy):
        if str(signal.get("method", "")).lower() != "ngram":
            continue
        name = str(signal["name"])
        route = signal_route_name(signal, routes)
        values = [str(value) for value in signal["keywords"]]
        rule_id = len(rules)
        rules.append({
            "threshold": float(signal.get("ngram_threshold", 0.4)),
            "threshold_milli": round(float(signal.get("ngram_threshold", 0.4)) * 1000),
            "priority": priorities.get(name, int(signal.get("priority", 0))),
            "route": ROUTE_IDS[route],
            "operator": OPERATORS[str(signal.get("operator", "OR")).upper()],
            "keyword_count": len(values),
        })
        keywords.extend({"text": value, "rule_id": rule_id} for value in values)
    return rules, keywords


def bm25_tables(path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    policy = load_policy(path)
    decision_routes, priorities = decision_keyword_routes(policy)
    rules: list[dict[str, object]] = []
    aliases: dict[str, dict[str, object]] = {}
    document_count = 0
    for signal in keyword_signals(policy):
        if str(signal.get("method", "")).lower() != "bm25":
            continue
        name = str(signal["name"])
        values = [str(value) for value in signal["keywords"]]
        corpus = [tokenize(value) for value in values]
        raw_corpus = [ascii_words(value) for value in values]
        avgdl = sum(map(len, corpus)) / len(corpus)
        df = Counter(token for document in corpus for token in set(document))
        start = document_count
        stem_vectors: dict[str, list[float]] = {}
        stem_surfaces: dict[str, set[str]] = defaultdict(set)
        for raw_tokens in raw_corpus:
            for surface in raw_tokens:
                stem_surfaces[stem_english(surface)].add(surface)
        for local_id, document in enumerate(corpus):
            frequencies = Counter(document)
            for stem, tf in frequencies.items():
                idf = math.log(1.0 + (len(corpus) - df[stem] + 0.5) / (df[stem] + 0.5))
                tf_norm = tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(document) / avgdl))
                vector = stem_vectors.setdefault(stem, [0.0] * MAX_DOCUMENTS)
                vector[start + local_id] = idf * tf_norm
        for stem, vector in stem_vectors.items():
            for surface in vocabulary_aliases(stem, stem_surfaces[stem]):
                existing = aliases.get(surface)
                if existing and existing["reference"] != vector:
                    raise ValueError(f"ambiguous BM25 surface alias: {surface}")
                aliases[surface] = {"reference": vector, "stopword": False}
        threshold_value = signal.get("bm25_threshold", 0.1)
        threshold = float(threshold_value)
        rules.append({
            "threshold": threshold,
            "threshold_fixed": threshold_fixed(threshold_value),
            "priority": priorities.get(name, int(signal.get("priority", 0))),
            "route": ROUTE_IDS[signal_route_name(signal, decision_routes)],
            "operator": OPERATORS[str(signal.get("operator", "OR")).upper()],
            "document_start": start,
            "document_count": len(values),
            "document_mask": ((1 << len(values)) - 1) << start,
        })
        document_count += len(values)
    for stopword in ENGLISH_STOP_WORDS:
        aliases.setdefault(stopword, {"reference": [0.0] * MAX_DOCUMENTS, "stopword": True})
    terms: list[dict[str, object]] = []
    seen_hashes: dict[int, str] = {}
    for surface, entry in aliases.items():
        hashed = token_hash(surface)
        if hashed in seen_hashes and seen_hashes[hashed] != surface:
            raise ValueError(f"FNV collision: {surface} and {seen_hashes[hashed]}")
        seen_hashes[hashed] = surface
        reference = list(entry["reference"])
        terms.append({
            "text": surface,
            "hash": hashed,
            "reference": reference,
            "fixed": [round(value * SCORE_SCALE) for value in reference],
            "stopword": bool(entry["stopword"]),
        })
    _, _, production_terms = parse_production_bm25(path)
    production_by_hash = {int(term["hash"]): term for term in production_terms}
    if set(production_by_hash) != {int(term["hash"]) for term in terms}:
        raise ValueError("ablation BM25 vocabulary differs from the production generated policy")
    for term in terms:
        production = production_by_hash[int(term["hash"])]
        if str(production["token"]) != str(term["text"]):
            raise ValueError(f"surface mismatch for {term['text']}")
        term["fixed"] = list(production["weights"])
        if bool(production["stopword"]) != bool(term["stopword"]):
            raise ValueError(f"stopword mismatch for {term['text']}")
    return rules, terms


def emit(ngram_policy: Path, bm25_policy: Path) -> str:
    ngram_rules, ngram_keywords = ngram_tables(ngram_policy)
    bm25_rules, bm25_terms = bm25_tables(bm25_policy)
    lines = [
        "/* Build-local file generated by benchmarks/ablation/generate_native_config.py. */",
        "#ifndef XSR_ABLATION_GENERATED_CONFIG_H",
        "#define XSR_ABLATION_GENERATED_CONFIG_H",
        f"#define ABL_NGRAM_RULE_COUNT {len(ngram_rules)}",
        f"#define ABL_NGRAM_KEYWORD_COUNT {len(ngram_keywords)}",
        f"#define ABL_BM25_RULE_COUNT {len(bm25_rules)}",
        f"#define ABL_BM25_TERM_COUNT {len(bm25_terms)}",
        "static const struct abl_ngram_rule abl_ngram_rules[] = {",
    ]
    for rule in ngram_rules:
        lines.append("  {%(threshold).17g, %(threshold_milli)dU, %(priority)dU, %(route)d, %(operator)d, %(keyword_count)d}," % rule)
    lines.append("};")
    lines.append("static const struct abl_ngram_keyword abl_ngram_keywords[] = {")
    for keyword in ngram_keywords:
        lines.append(f"  {{{c_string(str(keyword['text']))}, {keyword['rule_id']}}},")
    lines.extend(["};", "static const struct abl_bm25_rule abl_bm25_rules[] = {"])
    for rule in bm25_rules:
        lines.append("  {%(threshold).17g, %(threshold_fixed)dLL, %(priority)dU, %(route)d, %(operator)d, %(document_start)d, %(document_count)d, %(document_mask)dU}," % rule)
    lines.append("};")
    lines.append("static const struct abl_bm25_term abl_bm25_terms_by_hash[] = {")
    for term in sorted(bm25_terms, key=lambda item: int(item["hash"])):
        floats = ", ".join(f"{value:.17g}" for value in term["reference"])
        fixed = ", ".join(f"{value}LL" for value in term["fixed"])
        lines.append(f"  {{{c_string(str(term['text']))}, {term['hash']}U, {{{floats}}}, {{{fixed}}}, {int(term['stopword'])}}},")
    lines.append("};")
    lines.append("static const struct abl_bm25_term abl_bm25_terms_by_text[] = {")
    for term in sorted(bm25_terms, key=lambda item: str(item["text"])):
        floats = ", ".join(f"{value:.17g}" for value in term["reference"])
        fixed = ", ".join(f"{value}LL" for value in term["fixed"])
        lines.append(f"  {{{c_string(str(term['text']))}, {term['hash']}U, {{{floats}}}, {{{fixed}}}, {int(term['stopword'])}}},")
    lines.extend(["};", "#endif", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ngram-policy", type=Path, required=True)
    parser.add_argument("--bm25-policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(emit(args.ngram_policy, args.bm25_policy), encoding="utf-8")


if __name__ == "__main__":
    main()
