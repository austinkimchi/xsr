#!/usr/bin/env python3
"""Build the non-final transfer corpus while freezing validation/development."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from core import LABELS, read_jsonl, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-manifest", type=Path, required=True)
    parser.add_argument("--expanded-manifest", type=Path, required=True)
    parser.add_argument("--forbidden-final-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    full = list(read_jsonl(args.full_manifest))
    expanded = list(read_jsonl(args.expanded_manifest))
    forbidden = list(read_jsonl(args.forbidden_final_manifest))
    if any(row.get("student_split") == "final_test" for row in full + expanded):
        raise RuntimeError("recovery source manifests unexpectedly contain final-test rows")

    expanded_keys = {row["normalized_sha256"] for row in expanded}
    forbidden_keys = {row["normalized_sha256"] for row in forbidden}
    fixed_evaluation = [row for row in expanded
                        if row["student_split"] in ("validation", "test")]
    if Counter(row["student_split"] for row in fixed_evaluation) != {
        "validation": 72, "test": 343,
    }:
        raise RuntimeError("fixed validation/development split sizes changed")
    fixed_keys = {row["normalized_sha256"] for row in fixed_evaluation}
    if fixed_keys & forbidden_keys:
        raise RuntimeError("existing validation/development overlaps sealed final set")

    training = [dict(row) for row in expanded if row["student_split"] == "train"]
    additions = []
    for row in full:
        key = row["normalized_sha256"]
        if row.get("source_dataset") != "TIGER-Lab/MMLU-Pro":
            continue
        if key in expanded_keys or key in fixed_keys or key in forbidden_keys:
            continue
        addition = dict(row)
        addition["recovery_remapped_from_student_split"] = row["student_split"]
        addition["student_split"] = "train"
        additions.append(addition)
    training.extend(additions)
    output = training + fixed_evaluation
    keys = [row["normalized_sha256"] for row in output]
    if len(keys) != len(set(keys)):
        raise RuntimeError("recovery transfer manifest contains duplicate normalized prompts")
    if set(keys) & forbidden_keys:
        raise RuntimeError("recovery transfer manifest overlaps sealed final set")

    write_jsonl(args.output, output)
    counts = Counter(row["ground_truth_class"] for row in training)
    summary = {
        "full_manifest_sha256": hashlib.sha256(args.full_manifest.read_bytes()).hexdigest(),
        "expanded_manifest_sha256": hashlib.sha256(args.expanded_manifest.read_bytes()).hexdigest(),
        "forbidden_final_manifest_sha256": hashlib.sha256(
            args.forbidden_final_manifest.read_bytes()).hexdigest(),
        "output_manifest_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "sealed_final_overlap": 0,
        "existing_training_rows": len(training) - len(additions),
        "added_mmlu_pro_rows": len(additions),
        "training_rows": len(training),
        "validation_rows": 72,
        "development_rows": 343,
        "training_examples_per_class": {label: counts[label] for label in LABELS},
        "policy": (
            "All available MMLU-Pro rows not already used and not in the frozen 72-row "
            "validation, 343-row development holdout, or sealed final manifest are remapped "
            "to transfer training; existing Experiment C training rows are retained."
        ),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
