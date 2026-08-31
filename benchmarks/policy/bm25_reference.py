#!/usr/bin/env python3
"""Reference for VSR bm25 2.3 over XSR's bounded query transformation."""

from __future__ import annotations

import math
from collections import Counter

from generate_bm25_policy_header import SCORE_SCALE
from vsr_bm25_tokenizer import tokenize, tokenize_query


def keyword_scores(query: str, keywords: list[str]) -> list[float]:
    corpus = [tokenize(keyword) for keyword in keywords]
    if not corpus:
        return []
    avgdl = sum(map(len, corpus)) / len(corpus)
    df = Counter(token for document in corpus for token in set(document))
    query_tokens = tokenize_query(query)
    scores: list[float] = []
    for document in corpus:
        frequencies = Counter(document)
        score = 0.0
        for token in query_tokens:  # bm25 2.3 retains duplicate query embeddings.
            tf = frequencies.get(token, 0)
            if not tf:
                continue
            idf = math.log(1.0 + (len(corpus) - df[token] + 0.5) / (df[token] + 0.5))
            tf_norm = tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(document) / avgdl))
            score += idf * tf_norm
        scores.append(score)
    return scores


def fixed_scores(query: str, keywords: list[str]) -> list[int]:
    """Kernel representation: rounded per-term document weights accumulated in Q1e6."""
    corpus = [tokenize(keyword) for keyword in keywords]
    avgdl = sum(map(len, corpus)) / len(corpus)
    df = Counter(token for document in corpus for token in set(document))
    query_counts = Counter(tokenize_query(query))
    result = []
    for document in corpus:
        frequencies = Counter(document)
        total = 0
        for token, occurrences in query_counts.items():
            tf = frequencies.get(token, 0)
            if not tf:
                continue
            idf = math.log(1.0 + (len(corpus) - df[token] + 0.5) / (df[token] + 0.5))
            tf_norm = tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(document) / avgdl))
            total += round(idf * tf_norm * SCORE_SCALE) * occurrences
        result.append(total)
    return result


def rule_matches(query: str, keywords: list[str], operator: str, threshold: object) -> bool:
    threshold_value = float(threshold)
    matched = [score for score in keyword_scores(query, keywords) if score > 0 and score >= threshold_value]
    operator = operator.upper()
    if operator == "OR":
        return bool(matched)
    if operator == "AND":
        return len(matched) == len(keywords)
    if operator == "NOR":
        return not matched
    return False
