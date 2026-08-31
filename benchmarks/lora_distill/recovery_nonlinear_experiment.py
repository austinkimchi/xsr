#!/usr/bin/env python3
"""One bounded nonlinear fallback for the intent-distillation recovery ladder."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core import CLASS_COUNT, LABEL_TO_ID, feature_indices, read_jsonl
from rebalance_experiment import balanced_order, classification_report


@dataclass
class Example:
    features: np.ndarray
    label: int
    teacher_logits: np.ndarray


def aggregate(runs: list[dict], split: str, metric: str) -> dict[str, float]:
    values = [run[split][metric] for run in runs]
    return {"mean": float(np.mean(values)),
            "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[20260829, 20260830, 20260831])
    parser.add_argument("--width", type=int, default=8192)
    parser.add_argument("--hidden", type=int, default=32)
    parser.add_argument("--max-epochs", type=int, default=60)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.005)
    args = parser.parse_args()

    import torch
    import torch.nn.functional as functional

    rows = list(read_jsonl(args.manifest))
    if any(row.get("student_split") == "final_test" for row in rows):
        raise RuntimeError("sealed final rows are forbidden")
    targets = {row["normalized_sha256"]: row for row in read_jsonl(args.teacher_targets)}
    examples = {split: [] for split in ("train", "validation", "test")}
    for row in rows:
        examples[row["student_split"]].append(Example(
            feature_indices(row["prompt"], feature_count=args.width),
            LABEL_TO_ID[row["ground_truth_class"]],
            np.asarray(targets[row["normalized_sha256"]]["teacher_logits"], dtype=np.float32),
        ))
    if [len(examples[key]) for key in examples] != [11938, 72, 343]:
        raise RuntimeError("expected the frozen 11938/72/343 recovery splits")

    class Student(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embedding = torch.nn.EmbeddingBag(args.width, args.hidden, mode="sum")
            self.hidden_bias = torch.nn.Parameter(torch.zeros(args.hidden))
            self.output = torch.nn.Linear(args.hidden, CLASS_COUNT)
            torch.nn.init.normal_(self.embedding.weight, mean=0.0, std=0.001)
            torch.nn.init.kaiming_uniform_(self.output.weight, nonlinearity="relu")
            torch.nn.init.zeros_(self.output.bias)

        def forward(self, indices, offsets):
            hidden = functional.relu(self.embedding(indices, offsets) + self.hidden_bias)
            return self.output(hidden)

    def batches(split_rows: list[Example], order: list[int]):
        for start in range(0, len(order), args.batch_size):
            selected = [split_rows[index] for index in order[start:start + args.batch_size]]
            lengths = [len(item.features) for item in selected]
            yield (
                torch.from_numpy(np.concatenate([item.features for item in selected])),
                torch.from_numpy(np.cumsum([0] + lengths[:-1], dtype=np.int64)),
                torch.tensor([item.label for item in selected]),
                torch.from_numpy(np.stack([item.teacher_logits for item in selected])),
            )

    def metrics(model: Student, split_rows: list[Example]) -> dict:
        predicted, teacher, truth = [], [], []
        model.eval()
        with torch.inference_mode():
            for indices, offsets, labels, teacher_logits in batches(
                split_rows, list(range(len(split_rows)))
            ):
                logits = model(indices, offsets)
                predicted.extend(logits.argmax(1).tolist())
                teacher.extend(teacher_logits.argmax(1).tolist())
                truth.extend(labels.tolist())
        return {"teacher_agreement": float(np.mean(np.equal(predicted, teacher))),
                **classification_report(truth, predicted)}

    def fit(seed: int) -> dict:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.use_deterministic_algorithms(True)
        rng = random.Random(seed)
        model = Student()
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate,
                                      weight_decay=1e-4)
        best_state = None
        best_validation = None
        best_key = None
        no_improvement = 0
        losses = []
        for epoch in range(1, args.max_epochs + 1):
            model.train()
            total = 0.0
            for indices, offsets, labels, teacher_logits in batches(
                examples["train"], balanced_order(examples["train"], rng)
            ):
                optimizer.zero_grad()
                logits = model(indices, offsets)
                loss = functional.cross_entropy(logits, teacher_logits.argmax(1))
                loss.backward()
                optimizer.step()
                total += float(loss.detach()) * len(labels)
            losses.append(total / len(examples["train"]))
            validation = metrics(model, examples["validation"])
            key = (validation["teacher_agreement"], validation["accuracy"],
                   validation["macro_f1"])
            if best_key is None or key > best_key:
                best_key = key
                best_validation = {**validation, "epoch": epoch}
                best_state = {name: value.detach().clone()
                              for name, value in model.state_dict().items()}
                no_improvement = 0
            else:
                no_improvement += 1
            if no_improvement >= args.patience:
                break
        assert best_state is not None and best_validation is not None
        model.load_state_dict(best_state)
        return {
            "seed": seed,
            "epochs_ran": len(losses),
            "training_loss_first": losses[0],
            "training_loss_last": losses[-1],
            "training_loss_min": min(losses),
            "selected_validation": best_validation,
            "train": metrics(model, examples["train"]),
            "validation": metrics(model, examples["validation"]),
            "development": metrics(model, examples["test"]),
        }

    runs = [fit(seed) for seed in args.seeds]
    parameter_count = args.width * args.hidden + args.hidden + args.hidden * CLASS_COUNT + CLASS_COUNT
    report = {
        "experiment": "recovery bounded nonlinear fallback",
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "teacher_targets_sha256": hashlib.sha256(args.teacher_targets.read_bytes()).hexdigest(),
        "sealed_final_used": False,
        "representation": "8K FNV-1a normalized byte trigrams",
        "architecture": f"int8 embedding bag -> int32 accumulation/requantization -> H={args.hidden} ReLU -> int8 output linear -> int32 logits",
        "objective": "teacher-top1 cross-entropy",
        "parameter_count": parameter_count,
        "estimated_int8_state_bytes": args.width * args.hidden + args.hidden * CLASS_COUNT
            + (args.hidden + CLASS_COUNT) * 4,
        "quantization_note": "state estimate only; candidate was evaluated in FP32 and was not exported",
        "training": {
            "samples": len(examples["train"]), "sampling": "balanced minibatches",
            "optimizer": "AdamW", "learning_rate": args.learning_rate,
            "weight_decay": 1e-4, "max_epochs": args.max_epochs,
            "patience": args.patience, "selection": "validation teacher agreement",
            "seeds": args.seeds,
        },
        "seeds": runs,
        "aggregate": {
            split: {metric: aggregate(runs, split, metric)
                    for metric in ("teacher_agreement", "accuracy", "macro_f1")}
            for split in ("train", "validation", "development")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    print(json.dumps({"output": str(args.output), "aggregate": report["aggregate"]}, indent=2))


if __name__ == "__main__":
    main()
