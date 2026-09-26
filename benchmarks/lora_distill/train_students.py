#!/usr/bin/env python3
"""Train identical supervised and soft-target-distilled 14x4096 students."""

from __future__ import annotations

import argparse
import itertools
import json
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core import (CLASS_COUNT, FEATURE_COUNT, LABEL_TO_ID, feature_indices,
                  quantize_global, read_jsonl, write_kernel_model)


@dataclass
class Example:
    features: np.ndarray
    label: int
    teacher_logits: np.ndarray


def load_examples(manifest_path: Path, targets_path: Path) -> dict[str, list[Example]]:
    targets = {row["normalized_sha256"]: row for row in read_jsonl(targets_path)}
    split_rows: dict[str, list[Example]] = {"train": [], "validation": [], "test": []}
    for row in read_jsonl(manifest_path):
        target = targets.get(row["normalized_sha256"])
        if target is None:
            raise ValueError(f"missing teacher target for {row['normalized_sha256']}")
        label = LABEL_TO_ID.get(row.get("ground_truth_class"), -1)
        split_rows[row["student_split"]].append(Example(
            feature_indices(row["prompt"]), label,
            np.asarray(target["teacher_logits"], dtype=np.float32),
        ))
    if not split_rows["train"] or not split_rows["validation"] or not split_rows["test"]:
        raise ValueError("train, validation, and test splits must all be non-empty")
    return split_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=0.02)
    args = parser.parse_args()

    import torch
    import torch.nn.functional as functional

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)
    examples = load_examples(args.manifest, args.teacher_targets)

    class Student(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embedding = torch.nn.EmbeddingBag(FEATURE_COUNT, CLASS_COUNT, mode="sum")
            self.bias = torch.nn.Parameter(torch.zeros(CLASS_COUNT))
            torch.nn.init.zeros_(self.embedding.weight)

        def forward(self, indices, offsets):
            return self.embedding(indices, offsets) + self.bias

    def batches(rows: list[Example], shuffle: bool):
        order = list(range(len(rows)))
        if shuffle:
            random.shuffle(order)
        for start in range(0, len(order), args.batch_size):
            selected = [rows[index] for index in order[start : start + args.batch_size]]
            lengths = [len(item.features) for item in selected]
            offsets = np.cumsum([0] + lengths[:-1], dtype=np.int64)
            flat = np.concatenate([item.features for item in selected])
            yield (
                torch.from_numpy(flat), torch.from_numpy(offsets),
                torch.tensor([item.label for item in selected]),
                torch.from_numpy(np.stack([item.teacher_logits for item in selected])),
            )

    def metrics(model: Student, rows: list[Example]) -> dict[str, float]:
        predictions, teacher, truth = [], [], []
        model.eval()
        with torch.inference_mode():
            for indices, offsets, labels, teacher_logits in batches(rows, False):
                predictions.extend(model(indices, offsets).argmax(1).tolist())
                teacher.extend(teacher_logits.argmax(1).tolist())
                truth.extend(labels.tolist())
        labeled = [(a, b) for a, b in zip(predictions, truth) if b >= 0]
        return {
            "teacher_agreement": float(np.mean(np.equal(predictions, teacher))),
            "ground_truth_accuracy": float(np.mean([a == b for a, b in labeled])) if labeled else float("nan"),
        }

    def fit(alpha: float, temperature: float, distilled: bool) -> tuple[Student, dict]:
        model = Student()
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
        best_state, best_metrics = None, None
        for epoch in range(args.epochs):
            model.train()
            for indices, offsets, labels, teacher_logits in batches(examples["train"], True):
                optimizer.zero_grad()
                logits = model(indices, offsets)
                mask = labels >= 0
                hard = functional.cross_entropy(logits[mask], labels[mask]) if mask.any() else logits.sum() * 0
                if distilled:
                    soft = functional.kl_div(
                        functional.log_softmax(logits / temperature, dim=1),
                        functional.softmax(teacher_logits / temperature, dim=1),
                        reduction="batchmean",
                    ) * temperature * temperature
                    loss = alpha * hard + (1 - alpha) * soft
                else:
                    loss = hard
                loss.backward()
                optimizer.step()
            current = metrics(model, examples["validation"])
            score = (current["teacher_agreement"], current["ground_truth_accuracy"])
            previous = None if best_metrics is None else (
                best_metrics["teacher_agreement"], best_metrics["ground_truth_accuracy"]
            )
            if previous is None or score > previous:
                best_metrics = {**current, "epoch": epoch + 1}
                best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
        assert best_state is not None and best_metrics is not None
        model.load_state_dict(best_state)
        return model, best_metrics

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {"seed": args.seed, "test_used_for_selection": False, "candidates": []}
    supervised, supervised_validation = fit(1.0, 1.0, False)
    selected, selected_key, selected_config = None, None, None
    accuracy_floor = supervised_validation["ground_truth_accuracy"] - 0.05
    fallback = None
    for temperature, alpha in itertools.product((1.0, 2.0, 4.0), (0.25, 0.5)):
        model, validation = fit(alpha, temperature, True)
        candidate = {
            "temperature": temperature, "alpha": alpha, "validation": validation,
            "meets_accuracy_floor": validation["ground_truth_accuracy"] >= accuracy_floor,
        }
        summary["candidates"].append(candidate)
        key = (validation["teacher_agreement"], validation["ground_truth_accuracy"])
        fallback_key = (validation["ground_truth_accuracy"], validation["teacher_agreement"])
        if fallback is None or fallback_key > fallback[0]:
            fallback = (fallback_key, model, candidate)
        if candidate["meets_accuracy_floor"] and (selected_key is None or key > selected_key):
            selected, selected_key, selected_config = model, key, candidate
    if selected is None:
        assert fallback is not None
        _, selected, selected_config = fallback
    assert selected is not None

    def arrays(model: Student) -> tuple[np.ndarray, np.ndarray]:
        # EmbeddingBag stores [bucket,class]; canonical artifact stores [class,bucket].
        return (model.embedding.weight.detach().numpy().T.copy(), model.bias.detach().numpy().copy())

    supervised_weights, supervised_bias = arrays(supervised)
    distilled_weights, distilled_bias = arrays(selected)
    np.savez_compressed(args.output_dir / "supervised_float.npz", weights=supervised_weights, bias=supervised_bias)
    np.savez_compressed(args.output_dir / "distilled_float.npz", weights=distilled_weights, bias=distilled_bias)
    quantized = quantize_global(distilled_weights, distilled_bias)
    write_kernel_model(args.output_dir / "distilled_int8.xsrf", quantized)
    summary.update({
        "selected": selected_config,
        "validation_accuracy_floor": accuracy_floor,
        "supervised_validation": supervised_validation,
        "supervised_test": metrics(supervised, examples["test"]),
        "distilled_test": metrics(selected, examples["test"]),
        "int8_scale": quantized.scale,
    })
    (args.output_dir / "training_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
