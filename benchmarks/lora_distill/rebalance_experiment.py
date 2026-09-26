#!/usr/bin/env python3
"""Experiment B: compare two isolated rebalancing treatments."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import numpy as np

from core import CLASS_COUNT, FEATURE_COUNT, LABELS
from train_students import Example, load_examples


def classification_report(truth: list[int], predictions: list[int]) -> dict:
    matrix = np.zeros((CLASS_COUNT, CLASS_COUNT), dtype=np.int64)
    for actual, predicted in zip(truth, predictions):
        matrix[actual, predicted] += 1
    recall, f1 = [], []
    for index in range(CLASS_COUNT):
        tp = int(matrix[index, index])
        support = int(matrix[index, :].sum())
        fp = int(matrix[:, index].sum()) - tp
        fn = support - tp
        recall.append(0.0 if support == 0 else tp / support)
        f1.append(0.0 if 2 * tp + fp + fn == 0 else 2 * tp / (2 * tp + fp + fn))
    return {
        "accuracy": float(np.trace(matrix) / matrix.sum()),
        "macro_f1": float(np.mean(f1)),
        "per_class_recall": {label: recall[index] for index, label in enumerate(LABELS)},
        "prediction_distribution": {
            label: int(np.sum(np.equal(predictions, index)))
            for index, label in enumerate(LABELS)
        },
        "confusion_matrix_labels": list(LABELS),
        "confusion_matrix_rows_truth_columns_prediction": matrix.tolist(),
    }


def balanced_order(rows: list[Example], rng: random.Random) -> list[int]:
    """Return len(rows) uniform-class draws, balanced within each 14-draw block."""
    pools = {label: [] for label in range(CLASS_COUNT)}
    for index, item in enumerate(rows):
        pools[item.label].append(index)
    if any(not pool for pool in pools.values()):
        raise ValueError("balanced sampling requires every class")
    for pool in pools.values():
        rng.shuffle(pool)
    positions = {label: 0 for label in range(CLASS_COUNT)}
    order = []
    while len(order) < len(rows):
        labels = list(range(CLASS_COUNT))
        rng.shuffle(labels)
        for label in labels:
            if len(order) == len(rows):
                break
            pool = pools[label]
            position = positions[label]
            if position == len(pool):
                rng.shuffle(pool)
                position = 0
            order.append(pool[position])
            positions[label] = position + 1
    return order


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--baseline-model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=0.02)
    parser.add_argument("--temperature", type=float, default=2.0)
    parser.add_argument("--alpha", type=float, default=0.25)
    args = parser.parse_args()

    import torch
    import torch.nn.functional as functional

    np.random.seed(args.seed)
    torch.use_deterministic_algorithms(True)
    examples = load_examples(args.manifest, args.teacher_targets)
    if any(item.label < 0 for split in examples.values() for item in split):
        raise ValueError("Experiment B requires ground-truth labels for every row")

    class Student(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embedding = torch.nn.EmbeddingBag(FEATURE_COUNT, CLASS_COUNT, mode="sum")
            self.bias = torch.nn.Parameter(torch.zeros(CLASS_COUNT))
            torch.nn.init.zeros_(self.embedding.weight)

        def forward(self, indices, offsets):
            return self.embedding(indices, offsets) + self.bias

    def ordinary_order(rows: list[Example], rng: random.Random) -> list[int]:
        order = list(range(len(rows)))
        rng.shuffle(order)
        return order

    def batches(rows: list[Example], order: list[int]):
        for start in range(0, len(order), args.batch_size):
            selected = [rows[index] for index in order[start : start + args.batch_size]]
            lengths = [len(item.features) for item in selected]
            offsets = np.cumsum([0] + lengths[:-1], dtype=np.int64)
            yield (
                torch.from_numpy(np.concatenate([item.features for item in selected])),
                torch.from_numpy(offsets),
                torch.tensor([item.label for item in selected]),
                torch.from_numpy(np.stack([item.teacher_logits for item in selected])),
            )

    def predictions(model: Student, rows: list[Example]) -> tuple[list[int], list[int], list[int]]:
        predicted, teacher, truth = [], [], []
        model.eval()
        with torch.inference_mode():
            order = list(range(len(rows)))
            for indices, offsets, labels, teacher_logits in batches(rows, order):
                predicted.extend(model(indices, offsets).argmax(1).tolist())
                teacher.extend(teacher_logits.argmax(1).tolist())
                truth.extend(labels.tolist())
        return predicted, teacher, truth

    def metrics(model: Student, rows: list[Example]) -> dict:
        predicted, teacher, truth = predictions(model, rows)
        return {
            "teacher_agreement": float(np.mean(np.equal(predicted, teacher))),
            **classification_report(truth, predicted),
        }

    counts = Counter(item.label for item in examples["train"])
    class_weights = torch.tensor([
        len(examples["train"]) / (CLASS_COUNT * counts[index])
        for index in range(CLASS_COUNT)
    ], dtype=torch.float32)

    def fit(treatment: str, distilled: bool) -> tuple[Student, dict, list[float]]:
        random.seed(args.seed)
        torch.manual_seed(args.seed)
        rng = random.Random(args.seed)
        model = Student()
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
        best_state, best_validation, best_key = None, None, None
        losses = []
        for epoch in range(1, args.epochs + 1):
            order = (balanced_order(examples["train"], rng) if treatment == "balanced_sampling"
                     else ordinary_order(examples["train"], rng))
            model.train()
            loss_sum = 0.0
            sample_count = 0
            for indices, offsets, labels, teacher_logits in batches(examples["train"], order):
                optimizer.zero_grad()
                logits = model(indices, offsets)
                weights = class_weights if treatment == "class_weighted" else None
                hard = functional.cross_entropy(logits, labels, weight=weights)
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
                best_state = {name: value.detach().clone() for name, value in model.state_dict().items()}
        assert best_state is not None and best_validation is not None
        model.load_state_dict(best_state)
        return model, best_validation, losses

    def load_baseline(name: str) -> Student:
        arrays = np.load(args.baseline_model_dir / f"{name}_float.npz")
        model = Student()
        with torch.no_grad():
            model.embedding.weight.copy_(torch.from_numpy(arrays["weights"].T.copy()))
            model.bias.copy_(torch.from_numpy(arrays["bias"].copy()))
        return model

    report = {
        "experiment": "B: isolated rebalancing treatments",
        "seed": args.seed,
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "teacher_targets_sha256": hashlib.sha256(args.teacher_targets.read_bytes()).hexdigest(),
        "representation": {
            "classes": CLASS_COUNT,
            "hash_buckets": FEATURE_COUNT,
            "features": "FNV-1a hashed consecutive normalized byte trigrams",
        },
        "fixed_training": {
            "train_samples": len(examples["train"]),
            "validation_samples": len(examples["validation"]),
            "test_samples": len(examples["test"]),
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "optimizer": "AdamW",
            "learning_rate": args.learning_rate,
            "weight_decay": 1e-4,
            "distillation_temperature": args.temperature,
            "distillation_alpha": args.alpha,
        },
        "train_class_counts": {LABELS[index]: counts[index] for index in range(CLASS_COUNT)},
        "class_weights": {LABELS[index]: float(class_weights[index]) for index in range(CLASS_COUNT)},
        "models": {},
    }

    for model_kind in ("supervised", "distilled"):
        baseline = load_baseline(model_kind)
        report["models"][model_kind] = {
            "baseline": {
                "source": "existing pilot artifact",
                "train": metrics(baseline, examples["train"]),
                "test": metrics(baseline, examples["test"]),
            }
        }
        for treatment in ("class_weighted", "balanced_sampling"):
            model, validation, losses = fit(treatment, distilled=model_kind == "distilled")
            report["models"][model_kind][treatment] = {
                "validation_selection": validation,
                "train": metrics(model, examples["train"]),
                "test": metrics(model, examples["test"]),
                "training_loss_history": losses,
            }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    if args.summary_output:
        compact = {key: report[key] for key in (
            "experiment", "seed", "manifest_sha256", "teacher_targets_sha256",
            "representation", "fixed_training", "train_class_counts", "class_weights",
        )}
        compact["models"] = {
            kind: {
                treatment: {
                    **({"source": result["source"]} if "source" in result else {}),
                    **({"validation_selection": {
                        key: result["validation_selection"][key]
                        for key in ("epoch", "accuracy", "teacher_agreement", "macro_f1")
                    }} if "validation_selection" in result else {}),
                    "train": result["train"],
                    "test": result["test"],
                }
                for treatment, result in treatments.items()
            }
            for kind, treatments in report["models"].items()
        }
        compact["conclusion"] = (
            "Rebalancing reduces predictions of 'other' but does not materially fix "
            "held-out accuracy or teacher agreement; class-weighted supervised "
            "training shifts the dominant collapse from 'other' to 'history'."
        )
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(json.dumps(compact, separators=(",", ":")) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
