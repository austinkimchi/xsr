#!/usr/bin/env python3
"""Evaluate teacher, supervised, distilled, and quantized students."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from core import (CLASS_COUNT, LABELS, LABEL_TO_ID, float_scores, integer_scores,
                  predict, quantize_global, read_jsonl, read_kernel_model)


def classification_metrics(truth: list[int], predictions: list[int]) -> dict:
    matrix = np.zeros((CLASS_COUNT, CLASS_COUNT), dtype=np.int64)
    for actual, predicted in zip(truth, predictions):
        matrix[actual, predicted] += 1
    f1 = []
    for index in range(CLASS_COUNT):
        tp = matrix[index, index]
        fp = matrix[:, index].sum() - tp
        fn = matrix[index, :].sum() - tp
        f1.append(0.0 if 2 * tp + fp + fn == 0 else float(2 * tp / (2 * tp + fp + fn)))
    support = matrix.sum(axis=1)
    return {
        "accuracy": float(np.trace(matrix) / matrix.sum()) if matrix.sum() else None,
        "macro_f1": float(np.mean(f1)),
        "weighted_f1": float(np.average(f1, weights=support)) if support.sum() else None,
        "confusion_matrix": matrix.tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--int8-regression-threshold", type=float, default=0.005)
    args = parser.parse_args()
    targets = {row["normalized_sha256"]: row for row in read_jsonl(args.teacher_targets)}
    rows = [row for row in read_jsonl(args.manifest) if row["student_split"] == args.split]
    supervised = np.load(args.model_dir / "supervised_float.npz")
    distilled = np.load(args.model_dir / "distilled_float.npz")
    quantized = read_kernel_model(args.model_dir / "distilled_int8.xsrf")
    names = ("teacher", "supervised_float", "distilled_float", "distilled_int8")
    predictions = {name: [] for name in names}
    truth, fully_visible = [], 0
    for row in rows:
        target = targets[row["normalized_sha256"]]
        prompt = row["prompt"]
        fully_visible += len(prompt.encode("utf-8")) <= 16_384
        truth.append(LABEL_TO_ID[row["ground_truth_class"]])
        predictions["teacher"].append(int(np.argmax(target["teacher_logits"])))
        predictions["supervised_float"].append(predict(float_scores(prompt, supervised["weights"], supervised["bias"])))
        predictions["distilled_float"].append(predict(float_scores(prompt, distilled["weights"], distilled["bias"])))
        predictions["distilled_int8"].append(predict(integer_scores(prompt, quantized.weights, quantized.bias)))
    report = {
        "split": args.split, "samples": len(rows),
        "prompt_byte_limit": 16_384,
        "fully_visible_fraction": fully_visible / len(rows) if rows else None,
        "models": {},
        "float_to_int8_prediction_changes": int(np.sum(np.not_equal(
            predictions["distilled_float"], predictions["distilled_int8"]
        ))),
    }
    teacher = predictions["teacher"]
    for name in names:
        report["models"][name] = {
            "teacher_agreement": None if name == "teacher" else float(np.mean(np.equal(predictions[name], teacher))),
            **classification_metrics(truth, predictions[name]),
        }
    float_metrics = report["models"]["distilled_float"]
    int8_metrics = report["models"]["distilled_int8"]
    regression = max(
        float_metrics["accuracy"] - int8_metrics["accuracy"],
        float_metrics["teacher_agreement"] - int8_metrics["teacher_agreement"],
    )
    report["int8_max_primary_regression"] = regression
    if regression > args.int8_regression_threshold:
        diagnostic = quantize_global(distilled["weights"], distilled["bias"], bits=16)
        int16_predictions = [predict(integer_scores(row["prompt"], diagnostic.weights, diagnostic.bias)) for row in rows]
        report["int16_diagnostic"] = {
            "reason": f"int8 primary regression exceeded {args.int8_regression_threshold}",
            "teacher_agreement": float(np.mean(np.equal(int16_predictions, teacher))),
            **classification_metrics(truth, int16_predictions),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
