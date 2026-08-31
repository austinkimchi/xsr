#!/usr/bin/env python3
"""Evaluate locked 8K students once on the sealed independent final test."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from core import (
    LABELS,
    LABEL_TO_ID,
    feature_indices,
    integer_scores,
    predict,
    read_deployment_model,
    read_jsonl,
)
from rebalance_experiment import classification_report

HASH_WIDTH = 8192


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model_predictions(rows: list[dict], model: np.lib.npyio.NpzFile) -> list[int]:
    result = []
    for row in rows:
        indices = feature_indices(row["prompt"], feature_count=HASH_WIDTH)
        scores = model["bias"] + model["weights"][:, indices].sum(axis=1)
        result.append(predict(scores))
    return result


def metrics(truth: list[int], teacher: list[int], predictions: list[int]) -> dict:
    return {
        "teacher_agreement": float(np.mean(np.equal(predictions, teacher))),
        **classification_report(truth, predictions),
    }


def topic_pair_diagnostics(
    rows: list[dict], truth: list[int], predictions: dict[str, list[int]],
) -> dict:
    clusters: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        clusters[row["topic_cluster_id"]].append(index)
    if any(len(indices) != 2 for indices in clusters.values()):
        raise RuntimeError("each final-test topic must have exactly two prompt forms")

    result = {}
    for name, model_predictions in predictions.items():
        consistent = 0
        both_correct = 0
        at_least_one_correct = 0
        for indices in clusters.values():
            first, second = indices
            consistent += model_predictions[first] == model_predictions[second]
            correct = [
                model_predictions[index] == truth[index]
                for index in indices
            ]
            both_correct += all(correct)
            at_least_one_correct += any(correct)
        denominator = len(clusters)
        result[name] = {
            "same_prediction_across_forms": consistent / denominator,
            "both_forms_correct": both_correct / denominator,
            "at_least_one_form_correct": at_least_one_correct / denominator,
        }
    return result


def stratified_cluster_bootstrap(
    rows: list[dict], truth: list[int], predictions: dict[str, list[int]],
    seed: int, replicates: int,
) -> dict:
    clusters: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for index, row in enumerate(rows):
        clusters[row["ground_truth_class"]][row["topic_cluster_id"]].append(index)
    rng = np.random.default_rng(seed)
    samples = {
        name: {metric: [] for metric in ("accuracy", "teacher_agreement")}
        for name in predictions
    }
    for _ in range(replicates):
        selected = []
        for label in LABELS:
            label_clusters = list(clusters[label].values())
            draws = rng.integers(0, len(label_clusters), size=len(label_clusters))
            for draw in draws:
                selected.extend(label_clusters[int(draw)])
        selected_truth = [truth[index] for index in selected]
        selected_teacher = [predictions["teacher"][index] for index in selected]
        for name in samples:
            selected_predictions = [predictions[name][index] for index in selected]
            samples[name]["accuracy"].append(float(np.mean(np.equal(
                selected_predictions, selected_truth
            ))))
            samples[name]["teacher_agreement"].append(float(np.mean(np.equal(
                selected_predictions, selected_teacher
            ))))
    return {
        name: {
            metric: {
                "lower_95": float(np.quantile(values, 0.025)),
                "upper_95": float(np.quantile(values, 0.975)),
            }
            for metric, values in model_samples.items()
        }
        for name, model_samples in samples.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-summary", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--deployment-model", type=Path, required=True)
    parser.add_argument("--deployment-report", type=Path, required=True)
    parser.add_argument("--expanded-manifest", type=Path, required=True)
    parser.add_argument("--expanded-targets", type=Path, required=True)
    parser.add_argument("--hash-width-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    parser.add_argument(
        "--preflight-only", action="store_true",
        help="validate frozen artifacts and development reproduction without final predictions",
    )
    args = parser.parse_args()

    rows = list(read_jsonl(args.manifest))
    manifest_summary = json.loads(args.manifest_summary.read_text())
    if sha256(args.manifest) != manifest_summary["final_manifest_sha256"]:
        raise RuntimeError("sealed final manifest hash differs from its summary")
    if len(rows) != 1400 or any(row["student_split"] != "final_test" for row in rows):
        raise RuntimeError("expected exactly 1,400 sealed final-test rows")
    counts = {label: sum(row["ground_truth_class"] == label for row in rows) for label in LABELS}
    if set(counts.values()) != {100}:
        raise RuntimeError(f"final test is not balanced: {counts}")

    target_rows = list(read_jsonl(args.teacher_targets))
    targets = {row["normalized_sha256"]: row for row in target_rows}
    if len(targets) != len(rows) or set(targets) != {row["normalized_sha256"] for row in rows}:
        raise RuntimeError("final teacher targets are incomplete, duplicated, or out of scope")

    supervised_path = args.model_dir / "supervised_float.npz"
    distilled_path = args.model_dir / "distilled_float.npz"
    supervised = np.load(supervised_path)
    distilled = np.load(distilled_path)
    deployment_report = json.loads(args.deployment_report.read_text())
    deployed_int8 = read_deployment_model(args.deployment_model)
    if sha256(distilled_path) != deployment_report["selection"]["float_model_sha256"]:
        raise RuntimeError("final FP32 checkpoint differs from the deployment freeze")
    if sha256(args.deployment_model) != deployment_report["artifacts"]["int8_model_sha256"]:
        raise RuntimeError("final INT8 artifact differs from the deployment freeze")
    if deployment_report["selection"]["hash_buckets"] != HASH_WIDTH:
        raise RuntimeError("deployment freeze did not select the 8K architecture")
    for name, model in (("supervised", supervised), ("distilled", distilled)):
        if model["weights"].shape != (len(LABELS), HASH_WIDTH) or model["bias"].shape != (len(LABELS),):
            raise RuntimeError(f"{name} is not the locked 14x8K linear architecture")

    # Prove these exact local arrays reproduce the already-published Experiment D
    # metrics before opening the sealed final-test result.
    width_report = json.loads(args.hash_width_report.read_text())
    expanded_targets = {
        row["normalized_sha256"]: row for row in read_jsonl(args.expanded_targets)
    }
    expanded_test = [
        row for row in read_jsonl(args.expanded_manifest) if row["student_split"] == "test"
    ]
    expanded_truth = [LABEL_TO_ID[row["ground_truth_class"]] for row in expanded_test]
    expanded_teacher = [
        int(np.argmax(expanded_targets[row["normalized_sha256"]]["teacher_logits"]))
        for row in expanded_test
    ]
    baseline_reproduction = {}
    for name, model in (("supervised", supervised), ("distilled", distilled)):
        reproduced = metrics(
            expanded_truth, expanded_teacher, model_predictions(expanded_test, model)
        )
        expected = width_report["widths"][str(HASH_WIDTH)]["models"][name]["test"]
        for metric_name in ("accuracy", "teacher_agreement", "macro_f1"):
            if reproduced[metric_name] != expected[metric_name]:
                raise RuntimeError(
                    f"locked {name} model does not reproduce Experiment D {metric_name}"
                )
        baseline_reproduction[name] = {
            key: reproduced[key] for key in ("accuracy", "teacher_agreement", "macro_f1")
        }
    deployed_predictions = [
        predict(integer_scores(row["prompt"], deployed_int8.weights, deployed_int8.bias))
        for row in expanded_test
    ]
    deployed_reproduction = metrics(
        expanded_truth, expanded_teacher, deployed_predictions
    )
    expected_deployed = deployment_report["development_holdout"]["int8"]
    for metric_name in ("accuracy", "teacher_agreement", "macro_f1"):
        if deployed_reproduction[metric_name] != expected_deployed[metric_name]:
            raise RuntimeError(
                f"locked INT8 model does not reproduce deployment {metric_name}"
            )
    baseline_reproduction["distilled_int8"] = {
        key: deployed_reproduction[key]
        for key in ("accuracy", "teacher_agreement", "macro_f1")
    }
    if args.preflight_only:
        print(json.dumps({
            "status": "ready for explicit final-evaluation approval",
            "final_predictions_computed": False,
            "manifest_sha256": sha256(args.manifest),
            "deployment_model_sha256": sha256(args.deployment_model),
            "locked_baseline_reproduction": baseline_reproduction,
        }, indent=2))
        return

    truth = [LABEL_TO_ID[row["ground_truth_class"]] for row in rows]
    predictions = {
        "teacher": [int(np.argmax(targets[row["normalized_sha256"]]["teacher_logits"]))
                    for row in rows],
        "supervised": model_predictions(rows, supervised),
        "distilled": model_predictions(rows, distilled),
        "distilled_int8": [
            predict(integer_scores(row["prompt"], deployed_int8.weights, deployed_int8.bias))
            for row in rows
        ],
    }
    models = {
        "teacher": classification_report(truth, predictions["teacher"]),
        "supervised": metrics(truth, predictions["teacher"], predictions["supervised"]),
        "distilled": metrics(truth, predictions["teacher"], predictions["distilled"]),
        "distilled_int8": metrics(
            truth, predictions["teacher"], predictions["distilled_int8"]
        ),
    }
    models["teacher"]["teacher_agreement"] = None
    report = {
        "experiment": "sealed independent final test",
        "selection_status": (
            "8K linear architecture, FP32 weights, global INT8 quantization, and "
            "kernel model representation frozen before this evaluation"
        ),
        "manifest_sha256": sha256(args.manifest),
        "manifest_summary_sha256": sha256(args.manifest_summary),
        "teacher_targets_sha256": sha256(args.teacher_targets),
        "supervised_model_sha256": sha256(supervised_path),
        "distilled_model_sha256": sha256(distilled_path),
        "deployment_model_sha256": sha256(args.deployment_model),
        "deployment_report_sha256": sha256(args.deployment_report),
        "samples": len(rows),
        "topic_clusters": len(set(row["topic_cluster_id"] for row in rows)),
        "samples_per_class": counts,
        "independence": {
            "reference_manifest_sha256": manifest_summary["reference_manifest_sha256"],
            "exact_normalized_prompt_overlaps": manifest_summary["exact_normalized_prompt_overlaps"],
            "near_duplicate_threshold": manifest_summary["near_duplicate_threshold"],
            "near_duplicates_at_or_above_threshold": manifest_summary[
                "near_duplicates_at_or_above_threshold"
            ],
            "scope": manifest_summary["independence_scope"],
        },
        "locked_baseline_reproduction": baseline_reproduction,
        "models": models,
        "topic_pair_diagnostics": topic_pair_diagnostics(rows, truth, predictions),
        "stratified_topic_cluster_bootstrap": {
            "seed": args.seed,
            "replicates": args.bootstrap_replicates,
            "intervals": stratified_cluster_bootstrap(
                rows, truth, predictions, args.seed, args.bootstrap_replicates
            ),
        },
        "limitations": [
            "Prompts are synthetic category-neutral request forms over manually curated topics.",
            "Two prompt forms share each topic; confidence intervals resample topic clusters.",
            "Textual independence is verified against MMLU-Pro and the supplement, but semantic "
            "novelty against undocumented base-model pretraining corpora cannot be proven.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
