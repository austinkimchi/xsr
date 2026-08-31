#!/usr/bin/env python3
"""Diagnose the frozen 8K FP32 student's teacher-fidelity errors by split."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from core import (
    DEPLOYMENT_FEATURE_COUNT,
    LABELS,
    LABEL_TO_ID,
    float_scores,
    predict,
    read_jsonl,
    stable_softmax,
)
from rebalance_experiment import classification_report


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grouped_distribution(values: list[float]) -> dict:
    array = np.asarray(values, dtype=np.float64)
    if not len(array):
        return {"count": 0, "mean": None, "median": None, "p10": None, "p90": None}
    return {
        "count": len(values),
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
        "p10": float(np.quantile(array, 0.10)),
        "p90": float(np.quantile(array, 0.90)),
    }


def agreement_by_class(
    class_ids: list[int], teacher: list[int], student: list[int],
) -> dict:
    result = {}
    for class_id, label in enumerate(LABELS):
        indices = [index for index, value in enumerate(class_ids) if value == class_id]
        matches = sum(teacher[index] == student[index] for index in indices)
        result[label] = {
            "support": len(indices),
            "matches": matches,
            "agreement": matches / len(indices) if indices else None,
        }
    return result


def split_report(rows: list[dict], targets: dict[str, dict], model) -> dict:
    truth, teacher, student = [], [], []
    confidence = {"agreement": [], "disagreement": []}
    margin = {"agreement": [], "disagreement": []}
    for row in rows:
        target = targets[row["normalized_sha256"]]
        probabilities = stable_softmax(target["teacher_logits"])
        ordered = np.sort(probabilities)
        teacher_id = int(np.argmax(probabilities))
        student_id = predict(float_scores(row["prompt"], model["weights"], model["bias"]))
        group = "agreement" if teacher_id == student_id else "disagreement"
        truth.append(LABEL_TO_ID[row["ground_truth_class"]])
        teacher.append(teacher_id)
        student.append(student_id)
        confidence[group].append(float(ordered[-1]))
        margin[group].append(float(ordered[-1] - ordered[-2]))

    confusion = np.zeros((len(LABELS), len(LABELS)), dtype=np.int64)
    for teacher_id, student_id in zip(teacher, student):
        confusion[teacher_id, student_id] += 1
    pairs = Counter(
        (teacher_id, student_id)
        for teacher_id, student_id in zip(teacher, student)
        if teacher_id != student_id
    )
    dominant = [
        {
            "teacher_class": LABELS[teacher_id],
            "student_class": LABELS[student_id],
            "count": count,
            "fraction_of_disagreements": count / sum(pairs.values()),
        }
        for (teacher_id, student_id), count in pairs.most_common(20)
    ]
    teacher_metrics = classification_report(truth, teacher)
    student_metrics = classification_report(truth, student)
    return {
        "samples": len(rows),
        "student": {
            "teacher_agreement": float(np.mean(np.equal(student, teacher))),
            **student_metrics,
        },
        "teacher_ground_truth": teacher_metrics,
        "student_teacher_confusion": {
            "rows_teacher_columns_student": confusion.tolist(),
            "labels": list(LABELS),
        },
        "agreement_by_teacher_class": agreement_by_class(teacher, teacher, student),
        "agreement_by_ground_truth_class": agreement_by_class(truth, teacher, student),
        "teacher_confidence": {
            group: grouped_distribution(values) for group, values in confidence.items()
        },
        "teacher_top1_margin": {
            group: grouped_distribution(values) for group, values in margin.items()
        },
        "dominant_confusion_pairs": dominant,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--float-model", type=Path, required=True)
    parser.add_argument("--deployment-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    deployment = json.loads(args.deployment_report.read_text())
    if sha256(args.manifest) != deployment["selection"]["manifest_sha256"]:
        raise RuntimeError("diagnostic manifest differs from the frozen deployment corpus")
    if sha256(args.teacher_targets) != deployment["selection"]["teacher_targets_sha256"]:
        raise RuntimeError("diagnostic teacher targets differ from the frozen deployment corpus")
    if sha256(args.float_model) != deployment["selection"]["float_model_sha256"]:
        raise RuntimeError("diagnostic model differs from the frozen FP32 deployment checkpoint")

    rows = list(read_jsonl(args.manifest))
    if any(row["student_split"] == "final_test" for row in rows):
        raise RuntimeError("recovery diagnostics refuse sealed final-test rows")
    targets_list = list(read_jsonl(args.teacher_targets))
    targets = {row["normalized_sha256"]: row for row in targets_list}
    if len(targets) != len(targets_list) or any(
        row["normalized_sha256"] not in targets for row in rows
    ):
        raise RuntimeError("teacher targets are duplicated or incomplete")

    model = np.load(args.float_model)
    if model["weights"].shape != (len(LABELS), DEPLOYMENT_FEATURE_COUNT):
        raise RuntimeError("recovery diagnostic requires the frozen 8K linear model")
    report = {
        "experiment": "recovery baseline error diagnostics",
        "deployment_untouched": {
            "float_model_sha256": sha256(args.float_model),
            "int8_model_sha256": deployment["artifacts"]["int8_model_sha256"],
            "deployment_report_sha256": sha256(args.deployment_report),
        },
        "representation": "8K FNV-1a hashed normalized byte trigrams; FP32 linear student",
        "splits": {
            split: split_report(
                [row for row in rows if row["student_split"] == split], targets, model
            )
            for split in ("train", "validation", "test")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
