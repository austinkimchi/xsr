#!/usr/bin/env python3
"""Evaluate teacher/student agreement where no ground-truth intent exists."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from core import float_scores, integer_scores, predict, read_jsonl, read_kernel_model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    targets = {row["normalized_sha256"]: row for row in read_jsonl(args.teacher_targets)}
    supervised = np.load(args.model_dir / "supervised_float.npz")
    distilled = np.load(args.model_dir / "distilled_float.npz")
    quantized = read_kernel_model(args.model_dir / "distilled_int8.xsrf")
    teacher, predictions = [], {key: [] for key in ("supervised_float", "distilled_float", "distilled_int8")}
    rows = list(read_jsonl(args.manifest))
    for row in rows:
        prompt = row["prompt"]
        teacher.append(int(np.argmax(targets[row["normalized_sha256"]]["teacher_logits"])))
        predictions["supervised_float"].append(predict(float_scores(prompt, supervised["weights"], supervised["bias"])))
        predictions["distilled_float"].append(predict(float_scores(prompt, distilled["weights"], distilled["bias"])))
        predictions["distilled_int8"].append(predict(integer_scores(prompt, quantized.weights, quantized.bias)))
    report = {
        "dataset": "nvidia/SPEED-Bench",
        "samples": len(rows), "ground_truth_accuracy_available": False,
        "teacher_agreement": {key: float(np.mean(np.equal(value, teacher))) for key, value in predictions.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
