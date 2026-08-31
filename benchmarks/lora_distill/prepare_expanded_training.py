#!/usr/bin/env python3
"""Build Experiment C while preserving the fixed pilot holdout exactly."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from core import LABELS, read_jsonl, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-manifest", type=Path, required=True)
    parser.add_argument("--pilot-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--train-per-class", type=int, default=350)
    parser.add_argument("--seed", type=int, default=20260829)
    args = parser.parse_args()

    pilot = list(read_jsonl(args.pilot_manifest))
    full = list(read_jsonl(args.full_manifest))
    pilot_keys = {row["normalized_sha256"] for row in pilot}
    if len(pilot_keys) != len(pilot):
        raise ValueError("pilot manifest contains duplicate normalized prompts")
    fixed_test = [row for row in pilot if row["student_split"] == "test"]
    if len(fixed_test) != 343:
        raise ValueError(f"expected the fixed 343-row holdout, found {len(fixed_test)}")

    output = list(pilot)
    train_counts = Counter(row["ground_truth_class"] for row in output
                           if row["student_split"] == "train")
    candidates = {label: [] for label in LABELS}
    for row in full:
        key = row["normalized_sha256"]
        label = row["ground_truth_class"]
        if key not in pilot_keys and row["student_split"] == "test" and label in candidates:
            candidates[label].append(row)

    rng = random.Random(args.seed ^ 0x45585043)
    additions = []
    for label in LABELS:
        needed = args.train_per_class - train_counts[label]
        if needed < 0:
            raise ValueError(
                f"existing {label!r} training count {train_counts[label]} exceeds target "
                f"{args.train_per_class}"
            )
        if len(candidates[label]) < needed:
            raise ValueError(
                f"only {len(candidates[label])} unused {label!r} rows; need {needed}"
            )
        for row in rng.sample(candidates[label], needed):
            remapped = dict(row)
            remapped["student_split"] = "train"
            remapped["experiment_c_remapped_from_student_split"] = "test"
            additions.append(remapped)
    output.extend(additions)

    output_test = [row for row in output if row["student_split"] == "test"]
    if output_test != fixed_test:
        raise RuntimeError("fixed holdout rows changed during expanded-manifest construction")
    output_keys = [row["normalized_sha256"] for row in output]
    if len(output_keys) != len(set(output_keys)):
        raise RuntimeError("expanded manifest contains duplicate normalized prompts")

    write_jsonl(args.output, output)
    final_counts = Counter(row["ground_truth_class"] for row in output
                           if row["student_split"] == "train")
    summary = {
        "seed": args.seed,
        "full_manifest_sha256": hashlib.sha256(args.full_manifest.read_bytes()).hexdigest(),
        "pilot_manifest_sha256": hashlib.sha256(args.pilot_manifest.read_bytes()).hexdigest(),
        "expanded_manifest_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "fixed_holdout_rows": len(fixed_test),
        "fixed_holdout_normalized_sha256": [row["normalized_sha256"] for row in fixed_test],
        "original_train_rows": sum(1 for row in pilot if row["student_split"] == "train"),
        "added_train_rows": len(additions),
        "expanded_train_rows": sum(final_counts.values()),
        "validation_rows": sum(1 for row in output if row["student_split"] == "validation"),
        "train_examples_per_class": {label: final_counts[label] for label in LABELS},
        "source_split_policy": (
            "The fixed pilot test and validation rows are unchanged. Seeded rows from the "
            "remaining MMLU-Pro official-test pool are explicitly remapped to student train."
        ),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
