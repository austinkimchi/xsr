#!/usr/bin/env python3
"""Prepare a deduplicated SPEED-Bench agreement-only manifest."""

from __future__ import annotations
import argparse
from pathlib import Path
from core import normalized_prompt_key, write_jsonl

DATASET_ID = "nvidia/SPEED-Bench"
DATASET_REVISION = "487aa718444e816458d1a0a52bfce7a454285cf4"
DATASET_CONFIG = "qualitative"


def prompt_of(row: dict) -> str | None:
    turns = row.get("turns")
    if isinstance(turns, list):
        parts = [value.strip() for value in turns if isinstance(value, str) and value.strip()]
        if parts:
            return "\n\n".join(parts)
    for key in ("prompt", "question", "text", "instruction", "input"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from datasets import get_dataset_split_names, load_dataset
    output, seen = [], set()
    for split in get_dataset_split_names(DATASET_ID, DATASET_CONFIG, revision=DATASET_REVISION):
        for index, row in enumerate(load_dataset(
            DATASET_ID, DATASET_CONFIG, revision=DATASET_REVISION, split=split
        )):
            prompt = prompt_of(row)
            if not prompt:
                continue
            key = normalized_prompt_key(prompt)
            if key in seen:
                continue
            seen.add(key)
            output.append({
                "prompt": prompt, "source_dataset": DATASET_ID,
                "source_revision": DATASET_REVISION, "source_config": DATASET_CONFIG,
                "source_split": split,
                "source_index": index, "ground_truth_class": None,
                "student_split": "out_of_domain", "normalized_sha256": key,
            })
    write_jsonl(args.output, output)
    print(f"wrote {len(output)} SPEED-Bench prompts for agreement-only evaluation")


if __name__ == "__main__":
    main()
