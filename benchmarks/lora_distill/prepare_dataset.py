#!/usr/bin/env python3
"""Create explicit, leak-free MMLU-Pro/supplement distillation splits."""

from __future__ import annotations

import argparse
import random
from collections import Counter
from pathlib import Path

from core import LABEL_TO_ID, normalized_prompt_key, write_jsonl

MMLU_ID = "TIGER-Lab/MMLU-Pro"
MMLU_REVISION = "b189ec765aa7ed75c8acfea42df31fdae71f97be"
SUPPLEMENT_ID = "llm-semantic-router/category-classifier-supplement"
SUPPLEMENT_REVISION = "c51aed0d3a83a548270e835187cee30615188e60"


def prompt_of(row: dict) -> str | None:
    for key in ("question", "prompt", "text", "instruction", "input"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def label_of(row: dict) -> str | None:
    for key in ("category", "label", "domain"):
        value = row.get(key)
        if isinstance(value, str):
            label = value.strip().lower().replace("_", " ")
            if label in LABEL_TO_ID:
                return label
    return None


def load_rows(dataset_id: str, revision: str) -> dict[str, list[dict]]:
    from datasets import get_dataset_split_names, load_dataset

    result = {}
    for split in get_dataset_split_names(dataset_id, revision=revision):
        result[split] = list(load_dataset(dataset_id, revision=revision, split=split))
    return result


def source_to_student_split(source: str, source_split: str, rng: random.Random) -> str:
    lower = source_split.lower()
    if source == SUPPLEMENT_ID:
        draw = rng.random()
        return "train" if draw < 0.8 else "validation" if draw < 0.9 else "test"
    # MMLU-Pro publishes only validation and test. Preserve its entire official
    # test split for final evaluation and use the official validation examples
    # for fitting; supplement supplies an independent selection split.
    if source == MMLU_ID:
        return "test" if lower == "test" else "train"
    if lower in {"test", "validation", "dev"}:
        return "test" if lower == "test" else "validation"
    return "train"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260829)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    manifest, seen = [], set()
    specs = ((MMLU_ID, MMLU_REVISION), (SUPPLEMENT_ID, SUPPLEMENT_REVISION))
    for source, revision in specs:
        for source_split, rows in load_rows(source, revision).items():
            ordered = list(enumerate(rows))
            if source == SUPPLEMENT_ID:
                rng.shuffle(ordered)
            for source_index, row in ordered:
                prompt, label = prompt_of(row), label_of(row)
                if not prompt or label is None:
                    continue
                key = normalized_prompt_key(prompt)
                if key in seen:
                    continue
                seen.add(key)
                manifest.append({
                    "prompt": prompt, "source_dataset": source,
                    "source_revision": revision, "source_split": source_split,
                    "source_index": source_index, "ground_truth_class": label,
                    "student_split": source_to_student_split(source, source_split, rng),
                    "normalized_sha256": key,
                })
    write_jsonl(args.output, manifest)
    counts = Counter(row["student_split"] for row in manifest)
    print(f"wrote {len(manifest)} unique prompts to {args.output}: {dict(counts)}")


if __name__ == "__main__":
    main()
