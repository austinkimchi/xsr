#!/usr/bin/env python3
"""Experiment A: overfit the unchanged 4K FNV byte-trigram student."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import numpy as np

from core import CLASS_COUNT, FEATURE_COUNT, LABELS, LABEL_TO_ID, feature_indices, read_jsonl


def balanced_subset(rows: list[dict], per_class: int, seed: int) -> list[dict]:
    """Select a deterministic balanced subset without changing training batches."""
    by_label = {label: [] for label in LABELS}
    for row in rows:
        label = row.get("ground_truth_class")
        if row.get("student_split") == "train" and label in by_label:
            by_label[label].append(row)

    rng = random.Random(seed)
    selected = []
    for label in LABELS:
        candidates = by_label[label]
        if len(candidates) < per_class:
            raise ValueError(
                f"class {label!r} has {len(candidates)} training rows; "
                f"need {per_class}"
            )
        selected.extend(rng.sample(candidates, per_class))
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--examples-per-class", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=0.02)
    parser.add_argument("--target-accuracy", type=float, default=0.99)
    args = parser.parse_args()

    if not 10 <= args.examples_per_class <= 20:
        parser.error("--examples-per-class must be between 10 and 20")

    import torch
    import torch.nn.functional as functional

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)

    selected = balanced_subset(list(read_jsonl(args.manifest)), args.examples_per_class, args.seed)
    examples = [
        (feature_indices(row["prompt"]), LABEL_TO_ID[row["ground_truth_class"]])
        for row in selected
    ]

    class Student(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embedding = torch.nn.EmbeddingBag(FEATURE_COUNT, CLASS_COUNT, mode="sum")
            self.bias = torch.nn.Parameter(torch.zeros(CLASS_COUNT))
            torch.nn.init.zeros_(self.embedding.weight)

        def forward(self, indices, offsets):
            return self.embedding(indices, offsets) + self.bias

    def batches(shuffle: bool):
        order = list(range(len(examples)))
        if shuffle:
            random.shuffle(order)
        for start in range(0, len(order), args.batch_size):
            batch = [examples[index] for index in order[start : start + args.batch_size]]
            lengths = [len(features) for features, _ in batch]
            offsets = np.cumsum([0] + lengths[:-1], dtype=np.int64)
            flat = np.concatenate([features for features, _ in batch])
            yield (
                torch.from_numpy(flat),
                torch.from_numpy(offsets),
                torch.tensor([label for _, label in batch]),
            )

    def evaluate(model: Student) -> tuple[float, list[int], list[list[int]]]:
        predictions, truth = [], []
        model.eval()
        with torch.inference_mode():
            for indices, offsets, labels in batches(False):
                predictions.extend(model(indices, offsets).argmax(1).tolist())
                truth.extend(labels.tolist())
        confusion = [[0] * CLASS_COUNT for _ in range(CLASS_COUNT)]
        for actual, predicted in zip(truth, predictions):
            confusion[actual][predicted] += 1
        return float(np.mean(np.equal(predictions, truth))), predictions, confusion

    model = Student()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    loss_history = []
    accuracy_history = []
    first_target_epoch = None
    first_perfect_epoch = None
    for epoch in range(1, args.epochs + 1):
        model.train()
        loss_sum = 0.0
        sample_count = 0
        for indices, offsets, labels in batches(True):
            optimizer.zero_grad()
            loss = functional.cross_entropy(model(indices, offsets), labels)
            loss.backward()
            optimizer.step()
            loss_sum += float(loss.detach()) * len(labels)
            sample_count += len(labels)
        epoch_loss = loss_sum / sample_count
        accuracy, _, _ = evaluate(model)
        loss_history.append(epoch_loss)
        accuracy_history.append(accuracy)
        if first_target_epoch is None and accuracy >= args.target_accuracy:
            first_target_epoch = epoch
        if first_perfect_epoch is None and accuracy == 1.0:
            first_perfect_epoch = epoch

    final_accuracy, predictions, confusion = evaluate(model)
    prediction_counts = Counter(LABELS[prediction] for prediction in predictions)
    per_class_memorized = {
        label: confusion[index][index] == args.examples_per_class
        for index, label in enumerate(LABELS)
    }
    result = {
        "experiment": "A: balanced-subset overfit",
        "representation": {
            "classes": CLASS_COUNT,
            "hash_buckets": FEATURE_COUNT,
            "features": "FNV-1a hashed consecutive normalized byte trigrams",
        },
        "training": {
            "seed": args.seed,
            "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            "examples_per_class": args.examples_per_class,
            "subset_size": len(examples),
            "subset_normalized_sha256": [row["normalized_sha256"] for row in selected],
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "optimizer": "AdamW",
            "learning_rate": args.learning_rate,
            "weight_decay": 1e-4,
            "class_weighting": False,
            "balanced_minibatch_sampling": False,
            "train_and_evaluation_subset_identical": True,
        },
        "result": {
            "target_accuracy": args.target_accuracy,
            "first_target_epoch": first_target_epoch,
            "first_perfect_epoch": first_perfect_epoch,
            "final_training_accuracy": final_accuracy,
            "all_classes_memorized": all(per_class_memorized.values()),
            "per_class_memorized": per_class_memorized,
            "prediction_distribution": {
                label: prediction_counts.get(label, 0) for label in LABELS
            },
            "confusion_matrix_labels": list(LABELS),
            "confusion_matrix_rows_truth_columns_prediction": confusion,
            "loss": {
                "initial": loss_history[0],
                "final": loss_history[-1],
                "minimum": min(loss_history),
                "history": loss_history,
            },
            "accuracy_history": accuracy_history,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
