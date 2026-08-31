#!/usr/bin/env python3
"""Experiment E: compare the 8K linear student with one tiny nonlinear student."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core import CLASS_COUNT, LABELS, LABEL_TO_ID, feature_indices, read_jsonl
from rebalance_experiment import balanced_order, classification_report
from teacher_targets import ADAPTER_ID, ADAPTER_REVISION, BASE_ID, BASE_REVISION

HASH_WIDTH = 8192
HIDDEN_WIDTH = 16


@dataclass
class CapacityExample:
    features: np.ndarray
    label: int
    teacher_logits: np.ndarray


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--manifest-summary", type=Path, required=True)
    parser.add_argument("--hash-width-report", type=Path, required=True)
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
    width_report = json.loads(args.hash_width_report.read_text())
    manifest_summary = json.loads(args.manifest_summary.read_text())
    if width_report["manifest_sha256"] != manifest_hash:
        raise RuntimeError("8K linear baseline used a different manifest")
    if width_report["teacher_targets_sha256"] != targets_hash:
        raise RuntimeError("8K linear baseline used different teacher targets")
    holdout_keys = [row["normalized_sha256"] for row in rows if row["student_split"] == "test"]
    if holdout_keys != manifest_summary["fixed_holdout_normalized_sha256"]:
        raise RuntimeError("ordered fixed holdout differs from Experiments C and D")
    holdout_hash = hashlib.sha256("\n".join(holdout_keys).encode()).hexdigest()
    if holdout_hash != width_report["ordered_fixed_holdout_sha256"]:
        raise RuntimeError("ordered fixed holdout hash differs from Experiment D")

    examples: dict[str, list[CapacityExample]] = {}
    for split in ("train", "validation", "test"):
        examples[split] = []
        for row in rows:
            if row["student_split"] != split:
                continue
            target = targets[row["normalized_sha256"]]
            examples[split].append(CapacityExample(
                feature_indices(row["prompt"], feature_count=HASH_WIDTH),
                LABEL_TO_ID[row["ground_truth_class"]],
                np.asarray(target["teacher_logits"], dtype=np.float32),
            ))
    train_counts = Counter(item.label for item in examples["train"])
    if len(train_counts) != CLASS_COUNT or set(train_counts.values()) != {350}:
        raise RuntimeError(f"expanded training balance changed: {train_counts}")

    np.random.seed(args.seed)
    torch.use_deterministic_algorithms(True)

    class TinyMlpStudent(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embedding = torch.nn.EmbeddingBag(HASH_WIDTH, HIDDEN_WIDTH, mode="sum")
            self.hidden_bias = torch.nn.Parameter(torch.zeros(HIDDEN_WIDTH))
            self.output = torch.nn.Linear(HIDDEN_WIDTH, CLASS_COUNT)
            torch.nn.init.normal_(self.embedding.weight, mean=0.0, std=0.01)
            torch.nn.init.zeros_(self.hidden_bias)
            torch.nn.init.xavier_uniform_(self.output.weight)
            torch.nn.init.zeros_(self.output.bias)

        def forward(self, indices, offsets):
            hidden = torch.relu(self.embedding(indices, offsets) + self.hidden_bias)
            return self.output(hidden)

    def batches(split_rows: list[CapacityExample], order: list[int]):
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

    def metrics(model: TinyMlpStudent, split_rows: list[CapacityExample]) -> dict:
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

    def fit(distilled: bool) -> tuple[TinyMlpStudent, dict, list[float]]:
        torch.manual_seed(args.seed)
        rng = random.Random(args.seed)
        model = TinyMlpStudent()
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
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

    args.output_dir.mkdir(parents=True, exist_ok=True)
    mlp_models = {}
    for name, distilled in (("supervised", False), ("distilled", True)):
        model, validation, losses = fit(distilled)
        np.savez_compressed(
            args.output_dir / f"{name}_tiny_mlp_float.npz",
            embedding=model.embedding.weight.detach().numpy().copy(),
            hidden_bias=model.hidden_bias.detach().numpy().copy(),
            output_weight=model.output.weight.detach().numpy().copy(),
            output_bias=model.output.bias.detach().numpy().copy(),
        )
        mlp_models[name] = {
            "validation_selection": {
                key: validation[key]
                for key in ("epoch", "accuracy", "teacher_agreement", "macro_f1")
            },
            "train": metrics(model, examples["train"]),
            "test": metrics(model, examples["test"]),
            "training_loss_history": losses,
        }

    linear_parameters = CLASS_COUNT * HASH_WIDTH + CLASS_COUNT
    mlp_parameters = (HASH_WIDTH * HIDDEN_WIDTH + HIDDEN_WIDTH
                      + HIDDEN_WIDTH * CLASS_COUNT + CLASS_COUNT)
    report = {
        "experiment": "E: student model capacity",
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
            "hash_buckets": HASH_WIDTH,
            "train_samples": len(examples["train"]),
            "validation_samples": len(examples["validation"]),
            "test_samples": len(examples["test"]),
            "examples_per_class": {LABELS[index]: train_counts[index]
                                   for index in range(CLASS_COUNT)},
            "feature_type": "normalized byte trigrams hashed by FNV-1a",
            "treatment": "balanced minibatch sampling",
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "optimizer": "AdamW",
            "learning_rate": args.learning_rate,
            "weight_decay": 1e-4,
            "distillation_temperature": args.temperature,
            "distillation_alpha": args.alpha,
        },
        "architectures": {
            "linear": {
                "description": "8K EmbeddingBag directly to 14 logits plus bias",
                "parameter_count": linear_parameters,
                "float32_parameter_bytes": linear_parameters * 4,
                "int8_weight_bytes": HASH_WIDTH * CLASS_COUNT,
                "models": width_report["widths"][str(HASH_WIDTH)]["models"],
                "source": "reused Experiment D result",
            },
            "tiny_mlp_16": {
                "description": "8K EmbeddingBag to 16 hidden values, ReLU, 16x14 output",
                "hidden_width": HIDDEN_WIDTH,
                "parameter_count": mlp_parameters,
                "float32_parameter_bytes": mlp_parameters * 4,
                "int8_weight_bytes": HASH_WIDTH * HIDDEN_WIDTH + HIDDEN_WIDTH * CLASS_COUNT,
                "models": mlp_models,
                "source": "trained in Experiment E",
            },
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
