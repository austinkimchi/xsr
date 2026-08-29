#!/usr/bin/env python3
"""Experiment D: isolate FNV hash-width capacity at 4K, 8K, and 16K."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core import (CLASS_COUNT, LABELS, LABEL_TO_ID, PROMPT_BYTE_LIMIT,
                  feature_indices, fnv1a_trigram, normalize_bytes, read_jsonl)
from rebalance_experiment import balanced_order, classification_report
from teacher_targets import ADAPTER_ID, ADAPTER_REVISION, BASE_ID, BASE_REVISION


@dataclass
class WidthExample:
    features: np.ndarray
    label: int
    teacher_logits: np.ndarray


def collision_statistics(prompts: list[str], width: int) -> dict:
    unique_trigrams: set[bytes] = set()
    occurrences = 0
    for prompt in prompts:
        data = normalize_bytes(prompt)
        occurrences += max(0, len(data) - 2)
        unique_trigrams.update(data[index : index + 3] for index in range(max(0, len(data) - 2)))
    bucket_counts = Counter(fnv1a_trigram(trigram, width) for trigram in unique_trigrams)
    occupied = len(bucket_counts)
    collision_count = len(unique_trigrams) - occupied
    return {
        "training_trigram_occurrences": occurrences,
        "unique_training_byte_trigrams": len(unique_trigrams),
        "occupied_buckets": occupied,
        "bucket_occupancy_fraction": occupied / width,
        "unique_trigram_collisions": collision_count,
        "unique_trigram_collision_fraction": collision_count / len(unique_trigrams),
        "buckets_with_multiple_unique_trigrams": sum(value > 1 for value in bucket_counts.values()),
        "maximum_unique_trigrams_in_one_bucket": max(bucket_counts.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--manifest-summary", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=0.02)
    parser.add_argument("--temperature", type=float, default=2.0)
    parser.add_argument("--alpha", type=float, default=0.25)
    args = parser.parse_args()

    import torch
    import torch.nn.functional as functional

    manifest_hash = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    targets_hash = hashlib.sha256(args.teacher_targets.read_bytes()).hexdigest()
    rows = list(read_jsonl(args.manifest))
    targets = {row["normalized_sha256"]: row for row in read_jsonl(args.teacher_targets)}
    if len(targets) != len(rows):
        raise ValueError("teacher target count does not match expanded manifest")
    baseline = json.loads(args.baseline_report.read_text())
    manifest_summary = json.loads(args.manifest_summary.read_text())
    if baseline["manifest_sha256"] != manifest_hash:
        raise RuntimeError("4K baseline used a different manifest")
    if baseline["teacher_targets_sha256"] != targets_hash:
        raise RuntimeError("4K baseline used different teacher targets")
    holdout_keys = [row["normalized_sha256"] for row in rows if row["student_split"] == "test"]
    if holdout_keys != manifest_summary["fixed_holdout_normalized_sha256"]:
        raise RuntimeError("ordered fixed holdout differs from Experiment C")
    if len(holdout_keys) != 343:
        raise RuntimeError(f"expected 343 fixed holdout rows, found {len(holdout_keys)}")
    holdout_hash = hashlib.sha256("\n".join(holdout_keys).encode()).hexdigest()

    raw_by_split = {
        split: [row for row in rows if row["student_split"] == split]
        for split in ("train", "validation", "test")
    }
    train_counts = Counter(row["ground_truth_class"] for row in raw_by_split["train"])
    if len(train_counts) != CLASS_COUNT or set(train_counts.values()) != {350}:
        raise RuntimeError(f"expanded training balance changed: {train_counts}")
    np.random.seed(args.seed)
    torch.use_deterministic_algorithms(True)

    def width_examples(width: int) -> dict[str, list[WidthExample]]:
        result = {}
        for split, split_rows in raw_by_split.items():
            result[split] = [WidthExample(
                feature_indices(row["prompt"], feature_count=width),
                LABEL_TO_ID[row["ground_truth_class"]],
                np.asarray(targets[row["normalized_sha256"]]["teacher_logits"], dtype=np.float32),
            ) for row in split_rows]
        return result

    def train_width(width: int) -> dict:
        examples = width_examples(width)

        class Student(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.embedding = torch.nn.EmbeddingBag(width, CLASS_COUNT, mode="sum")
                self.bias = torch.nn.Parameter(torch.zeros(CLASS_COUNT))
                torch.nn.init.zeros_(self.embedding.weight)

            def forward(self, indices, offsets):
                return self.embedding(indices, offsets) + self.bias

        def batches(split_rows: list[WidthExample], order: list[int]):
            for start in range(0, len(order), args.batch_size):
                selected = [split_rows[index] for index in order[start : start + args.batch_size]]
                lengths = [len(item.features) for item in selected]
                offsets = np.cumsum([0] + lengths[:-1], dtype=np.int64)
                yield (
                    torch.from_numpy(np.concatenate([item.features for item in selected])),
                    torch.from_numpy(offsets),
                    torch.tensor([item.label for item in selected]),
                    torch.from_numpy(np.stack([item.teacher_logits for item in selected])),
                )

        def metrics(model: Student, split_rows: list[WidthExample]) -> dict:
            predicted, teacher, truth = [], [], []
            model.eval()
            with torch.inference_mode():
                for indices, offsets, labels, teacher_logits in batches(
                    split_rows, list(range(len(split_rows)))
                ):
                    predicted.extend(model(indices, offsets).argmax(1).tolist())
                    teacher.extend(teacher_logits.argmax(1).tolist())
                    truth.extend(labels.tolist())
            return {
                "teacher_agreement": float(np.mean(np.equal(predicted, teacher))),
                **classification_report(truth, predicted),
            }

        def fit(distilled: bool) -> tuple[Student, dict, list[float]]:
            torch.manual_seed(args.seed)
            rng = random.Random(args.seed)
            model = Student()
            optimizer = torch.optim.AdamW(
                model.parameters(), lr=args.learning_rate, weight_decay=1e-4
            )
            best_state, best_validation, best_key = None, None, None
            losses = []
            for epoch in range(1, args.epochs + 1):
                order = balanced_order(examples["train"], rng)
                model.train()
                loss_sum = 0.0
                sample_count = 0
                for indices, offsets, labels, teacher_logits in batches(examples["train"], order):
                    optimizer.zero_grad()
                    logits = model(indices, offsets)
                    hard = functional.cross_entropy(logits, labels)
                    if distilled:
                        soft = functional.kl_div(
                            functional.log_softmax(logits / args.temperature, dim=1),
                            functional.softmax(teacher_logits / args.temperature, dim=1),
                            reduction="batchmean",
                        ) * args.temperature * args.temperature
                        loss = args.alpha * hard + (1 - args.alpha) * soft
                    else:
                        loss = hard
                    loss.backward()
                    optimizer.step()
                    loss_sum += float(loss.detach()) * len(labels)
                    sample_count += len(labels)
                losses.append(loss_sum / sample_count)
                validation = metrics(model, examples["validation"])
                key = (validation["teacher_agreement"], validation["accuracy"])
                if best_key is None or key > best_key:
                    best_key = key
                    best_validation = {**validation, "epoch": epoch}
                    best_state = {
                        name: value.detach().clone() for name, value in model.state_dict().items()
                    }
            assert best_state is not None and best_validation is not None
            model.load_state_dict(best_state)
            return model, best_validation, losses

        width_result = {}
        width_dir = args.output_dir / str(width)
        width_dir.mkdir(parents=True, exist_ok=True)
        for name, distilled in (("supervised", False), ("distilled", True)):
            model, validation, losses = fit(distilled)
            weights = model.embedding.weight.detach().numpy().T.copy()
            bias = model.bias.detach().numpy().copy()
            np.savez_compressed(width_dir / f"{name}_float.npz", weights=weights, bias=bias)
            width_result[name] = {
                "validation_selection": {
                    key: validation[key]
                    for key in ("epoch", "accuracy", "teacher_agreement", "macro_f1")
                },
                "train": metrics(model, examples["train"]),
                "test": metrics(model, examples["test"]),
                "training_loss_history": losses,
            }
        return width_result

    widths = {}
    for width in (4096, 8192, 16384):
        parameter_count = CLASS_COUNT * width + CLASS_COUNT
        widths[str(width)] = {
            "parameter_count": parameter_count,
            "float32_parameter_bytes": parameter_count * 4,
            "int8_weight_bytes": CLASS_COUNT * width,
            "estimated_xsrf_bytes": CLASS_COUNT * width + CLASS_COUNT * 4
                                    + struct.calcsize("<8sIIIIId"),
            "collision_statistics": collision_statistics(
                [row["prompt"] for row in raw_by_split["train"]], width
            ),
            "models": baseline["models"] if width == 4096 else train_width(width),
            "source": "reused Experiment C result" if width == 4096 else "trained in Experiment D",
        }

    report = {
        "experiment": "D: FNV hash-width capacity",
        "seed": args.seed,
        "manifest_sha256": manifest_hash,
        "teacher_targets_sha256": targets_hash,
        "ordered_fixed_holdout_sha256": holdout_hash,
        "fixed_holdout_rows": len(holdout_keys),
        "teacher": {
            "base_model": BASE_ID,
            "base_revision": BASE_REVISION,
            "adapter": ADAPTER_ID,
            "adapter_revision": ADAPTER_REVISION,
            "frozen": True,
        },
        "fixed_training": {
            "train_samples": len(raw_by_split["train"]),
            "validation_samples": len(raw_by_split["validation"]),
            "test_samples": len(raw_by_split["test"]),
            "examples_per_class": {label: train_counts[label] for label in LABELS},
            "feature_type": "normalized byte trigrams hashed by FNV-1a",
            "architecture": "linear EmbeddingBag plus bias",
            "treatment": "balanced minibatch sampling",
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "optimizer": "AdamW",
            "learning_rate": args.learning_rate,
            "weight_decay": 1e-4,
            "distillation_temperature": args.temperature,
            "distillation_alpha": args.alpha,
            "quantization_assumption": "one global symmetric int8 scale; float metrics reported",
        },
        "widths": widths,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
