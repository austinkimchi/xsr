#!/usr/bin/env python3
"""Freeze the selected 8K student and quantify development-set INT8 loss."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np

from core import (
    CLASS_COUNT,
    DEPLOYMENT_FEATURE_COUNT,
    LABEL_TO_ID,
    PROMPT_BYTE_LIMIT,
    float_scores,
    integer_scores,
    overflow_bound,
    predict,
    quantize_global,
    read_jsonl,
    read_deployment_model,
    write_kernel_model,
)
from rebalance_experiment import classification_report

SELECTED_FLOAT_SHA256 = "828859aec3ca5e93a77ff605a81d49bf6776dc64851e0bc931d9bc2f7ea62560"
MODEL_HEADER_FORMAT = "<8sIIIIId"
TEACHER_BASE_WEIGHT_BYTES = 615_591_696
TEACHER_ADAPTER_WEIGHT_BYTES = 27_098_736
TEACHER_BASE_WEIGHT_SHA256 = "6235e1c429e6c209f93def470518e9148618deff86edc3b5fd4fd5baf87a6c38"
TEACHER_ADAPTER_WEIGHT_SHA256 = "aa6fc5a99cb5517787073f4e4824d12a8a67ad7a10393a33a11f394836a8ee37"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model_metrics(
    truth: list[int], teacher: list[int], predictions: list[int],
) -> dict:
    return {
        "teacher_agreement": float(np.mean(np.equal(predictions, teacher))),
        **classification_report(truth, predictions),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--hash-width-report", type=Path, required=True)
    parser.add_argument("--float-model", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    width_report = json.loads(args.hash_width_report.read_text())
    if sha256(args.manifest) != width_report["manifest_sha256"]:
        raise RuntimeError("manifest differs from Experiment D")
    if sha256(args.teacher_targets) != width_report["teacher_targets_sha256"]:
        raise RuntimeError("teacher targets differ from Experiment D")
    if sha256(args.float_model) != SELECTED_FLOAT_SHA256:
        raise RuntimeError("float checkpoint differs from the selected 8K distilled model")

    float_model = np.load(args.float_model)
    weights = np.asarray(float_model["weights"])
    bias = np.asarray(float_model["bias"])
    if weights.shape != (CLASS_COUNT, DEPLOYMENT_FEATURE_COUNT):
        raise RuntimeError(f"unexpected selected weight shape: {weights.shape}")
    if bias.shape != (CLASS_COUNT,):
        raise RuntimeError(f"unexpected selected bias shape: {bias.shape}")
    if weights.dtype != np.float32 or bias.dtype != np.float32:
        raise RuntimeError("selected model parameters must be float32")

    rows = [
        row for row in read_jsonl(args.manifest)
        if row["student_split"] == "test"
    ]
    if len(rows) != width_report["fixed_holdout_rows"] or len(rows) != 343:
        raise RuntimeError("development holdout is not the fixed 343-row split")
    ordered_keys = [row["normalized_sha256"] for row in rows]
    holdout_hash = hashlib.sha256("\n".join(ordered_keys).encode()).hexdigest()
    if holdout_hash != width_report["ordered_fixed_holdout_sha256"]:
        raise RuntimeError("ordered development holdout differs from Experiment D")

    target_rows = list(read_jsonl(args.teacher_targets))
    targets = {row["normalized_sha256"]: row for row in target_rows}
    if len(targets) != len(target_rows):
        raise RuntimeError("teacher targets contain duplicate prompt keys")
    if any(key not in targets for key in ordered_keys):
        raise RuntimeError("teacher targets do not cover the development holdout")

    truth = [LABEL_TO_ID[row["ground_truth_class"]] for row in rows]
    teacher = [
        int(np.argmax(targets[row["normalized_sha256"]]["teacher_logits"]))
        for row in rows
    ]
    float_predictions = [
        predict(float_scores(row["prompt"], weights, bias)) for row in rows
    ]
    float_metrics = model_metrics(truth, teacher, float_predictions)
    expected = width_report["widths"][str(DEPLOYMENT_FEATURE_COUNT)]["models"][
        "distilled"
    ]["test"]
    for metric in ("accuracy", "teacher_agreement", "macro_f1"):
        if float_metrics[metric] != expected[metric]:
            raise RuntimeError(f"selected float model does not reproduce {metric}")

    quantized = quantize_global(weights, bias)
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    write_kernel_model(args.output_model, quantized)
    deployed = read_deployment_model(args.output_model)
    if not np.array_equal(deployed.weights, quantized.weights):
        raise RuntimeError("serialized INT8 weights do not round-trip exactly")
    if not np.array_equal(deployed.bias, quantized.bias):
        raise RuntimeError("serialized INT8 bias does not round-trip exactly")
    int8_predictions = [
        predict(integer_scores(row["prompt"], deployed.weights, deployed.bias))
        for row in rows
    ]
    int8_metrics = model_metrics(truth, teacher, int8_predictions)

    parameter_count = weights.size + bias.size
    header_bytes = struct.calcsize(MODEL_HEADER_FORMAT)
    raw_weight_bytes = deployed.weights.nbytes
    bias_bytes = deployed.bias.nbytes
    expected_file_bytes = header_bytes + raw_weight_bytes + bias_bytes
    if args.output_model.stat().st_size != expected_file_bytes:
        raise RuntimeError("serialized model byte size does not match its layout")
    teacher_weight_bytes = TEACHER_BASE_WEIGHT_BYTES + TEACHER_ADAPTER_WEIGHT_BYTES

    metric_deltas = {
        metric: int8_metrics[metric] - float_metrics[metric]
        for metric in ("accuracy", "macro_f1", "teacher_agreement")
    }
    report = {
        "experiment": "pre-final canonical deployment freeze",
        "gate_status": "architecture, weights, quantization, and model format frozen",
        "sealed_final_evaluation_run_by_this_tool": False,
        "selection": {
            "student": "distilled 8K linear FNV byte-trigram student",
            "classes": CLASS_COUNT,
            "hash_buckets": DEPLOYMENT_FEATURE_COUNT,
            "prompt_byte_limit": PROMPT_BYTE_LIMIT,
            "architecture": "one 14-value INT8 map lookup per byte trigram plus INT32 bias",
            "rationale": (
                "8K is the smallest width that improved both distilled held-out accuracy "
                "and teacher agreement over 4K; 16K doubles state again and regressed for "
                "the distilled objective"
            ),
            "float_model_sha256": sha256(args.float_model),
            "manifest_sha256": sha256(args.manifest),
            "teacher_targets_sha256": sha256(args.teacher_targets),
            "ordered_development_holdout_sha256": holdout_hash,
        },
        "independent_feature_path": {
            "input": "decoded prompt bytes only",
            "normalization": "private ASCII A-Z to a-z fold",
            "features": "private consecutive byte-trigram state",
            "hash": "private 32-bit FNV-1a computation",
            "lookup": "private xdp_distill_weights BPF map",
            "accumulation": "private 14-element INT32 score state",
            "deterministic_keyword_intermediates_reused": False,
        },
        "quantization": {
            "scheme": "one global symmetric INT8 weight scale; bias scaled to INT32",
            "scale": deployed.scale,
            "maximum_absolute_float_weight": float(np.max(np.abs(weights))),
            "maximum_absolute_int8_weight": int(np.max(np.abs(deployed.weights.astype(np.int16)))),
            "maximum_absolute_int32_bias": int(np.max(np.abs(deployed.bias.astype(np.int64)))),
            "proven_int32_score_bound": overflow_bound(deployed.bias),
        },
        "development_holdout": {
            "samples": len(rows),
            "float": float_metrics,
            "int8": int8_metrics,
            "int8_minus_float": metric_deltas,
            "prediction_changes": int(np.sum(np.not_equal(
                float_predictions, int8_predictions
            ))),
        },
        "footprint": {
            "parameter_count": parameter_count,
            "fp32_parameter_bytes": weights.nbytes + bias.nbytes,
            "int8_parameter_bytes": raw_weight_bytes + bias_bytes,
            "int8_weight_bytes": raw_weight_bytes,
            "int32_bias_bytes": bias_bytes,
            "xsrf_header_bytes": header_bytes,
            "xsrf_file_bytes": args.output_model.stat().st_size,
            "bpf_weight_map_logical_value_bytes": raw_weight_bytes,
            "bpf_weight_map_8_byte_aligned_value_storage": (
                DEPLOYMENT_FEATURE_COUNT * 16
            ),
            "bpf_map_storage_note": (
                "aligned value storage excludes map metadata and allocator overhead; "
                "live map memory is measured during parity"
            ),
            "pinned_teacher_weight_artifacts": {
                "base_safetensors_bytes": TEACHER_BASE_WEIGHT_BYTES,
                "base_safetensors_sha256": TEACHER_BASE_WEIGHT_SHA256,
                "adapter_safetensors_bytes": TEACHER_ADAPTER_WEIGHT_BYTES,
                "adapter_safetensors_sha256": TEACHER_ADAPTER_WEIGHT_SHA256,
                "combined_weight_bytes": teacher_weight_bytes,
            },
            "teacher_weights_to_xsrf_size_ratio": (
                teacher_weight_bytes / args.output_model.stat().st_size
            ),
        },
        "artifacts": {
            "int8_model_sha256": sha256(args.output_model),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
