#!/usr/bin/env python3
"""Recovery experiments for linear byte-trigram teacher fidelity.

This is deliberately userspace-only.  It never reads or writes the sealed final
set, deployment artifact, BPF maps, or performance benchmark outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core import (CLASS_COUNT, FNV_OFFSET, FNV_PRIME, LABEL_TO_ID, PROMPT_BYTE_LIMIT,
                  feature_indices, normalize_bytes, read_jsonl)
from rebalance_experiment import balanced_order, classification_report


@dataclass
class Example:
    features: np.ndarray
    label: int
    teacher_logits: np.ndarray


def exact_training_vocabulary(rows: list[dict]) -> dict[bytes, int]:
    """Return a collision-free ID for every normalized training trigram."""
    trigrams: set[bytes] = set()
    for row in rows:
        data = normalize_bytes(row["prompt"])
        trigrams.update(data[index:index + 3] for index in range(max(0, len(data) - 2)))
    return {trigram: index for index, trigram in enumerate(sorted(trigrams))}


def exact_features(prompt: str, vocabulary: dict[bytes, int]) -> np.ndarray:
    data = normalize_bytes(prompt)
    return np.fromiter(
        (vocabulary[trigram] for index in range(max(0, len(data) - 2))
         if (trigram := data[index:index + 3]) in vocabulary),
        dtype=np.int64,
    )


def word_tokens(prompt: str) -> list[bytes]:
    """Bounded ASCII-alphanumeric words over the kernel-normalized byte stream."""
    data = normalize_bytes(prompt)
    tokens = []
    start = None
    for index, value in enumerate(data):
        is_word = 48 <= value <= 57 or 97 <= value <= 122
        if is_word and start is None:
            start = index
        elif not is_word and start is not None:
            tokens.append(data[start:index])
            start = None
    if start is not None:
        tokens.append(data[start:])
    return tokens


def fnv_bytes(data: bytes, width: int, namespace: int) -> int:
    value = FNV_OFFSET
    for byte in bytes((namespace,)) + data:
        value ^= byte
        value = (value * FNV_PRIME) & 0xFFFFFFFF
    return value & (width - 1)


def word_features(prompt: str, width: int, kind: str) -> np.ndarray:
    tokens = word_tokens(prompt)
    unigrams = [fnv_bytes(token, width, 1) for token in tokens]
    bigrams = [fnv_bytes(left + b"\x00" + right, width, 2)
               for left, right in zip(tokens, tokens[1:])]
    if kind == "word_unigram":
        values = unigrams
    elif kind == "word_bigram":
        values = bigrams
    elif kind == "mixed":
        values = feature_indices(prompt, feature_count=width).tolist() + unigrams + bigrams
    else:
        raise ValueError(kind)
    return np.asarray(values, dtype=np.int64)


def mean_std(values: list[float]) -> dict[str, float]:
    return {
        "mean": float(np.mean(values)),
        "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--teacher-targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("diagnostic", "objectives", "learning_curve",
                                            "features"), required=True)
    parser.add_argument("--learning-curve-sizes", type=int, nargs="+",
                        default=[4900, 7000, 9000, 11938])
    parser.add_argument("--seeds", type=int, nargs="+", default=[20260829, 20260830, 20260831])
    parser.add_argument("--max-epochs", type=int, default=60)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.02)
    args = parser.parse_args()

    import torch
    import torch.nn.functional as functional

    rows = list(read_jsonl(args.manifest))
    if any(row.get("student_split") == "final_test" for row in rows):
        raise RuntimeError("sealed final rows are forbidden in recovery experiments")
    targets = {row["normalized_sha256"]: row for row in read_jsonl(args.teacher_targets)}
    if set(targets) != {row["normalized_sha256"] for row in rows}:
        raise RuntimeError("teacher targets and manifest do not match exactly")
    raw = {split: [row for row in rows if row["student_split"] == split]
           for split in ("train", "validation", "test")}
    expected_train = 11938 if args.phase in ("learning_curve", "features") else 4900
    if [len(raw[split]) for split in raw] != [expected_train, 72, 343]:
        raise RuntimeError(f"expected fixed {expected_train}/72/343 recovery splits")

    vocabulary = exact_training_vocabulary(raw["train"])

    def make_examples(kind: str, width: int, selected_raw=None) -> dict[str, list[Example]]:
        selected_raw = raw if selected_raw is None else selected_raw
        result = {}
        for split, split_rows in selected_raw.items():
            result[split] = []
            for row in split_rows:
                if kind == "exact":
                    features = exact_features(row["prompt"], vocabulary)
                elif kind == "hashed":
                    features = feature_indices(row["prompt"], feature_count=width)
                else:
                    features = word_features(row["prompt"], width, kind)
                result[split].append(Example(
                    features=features,
                    label=LABEL_TO_ID[row["ground_truth_class"]],
                    teacher_logits=np.asarray(
                        targets[row["normalized_sha256"]]["teacher_logits"], dtype=np.float32
                    ),
                ))
        return result

    class Student(torch.nn.Module):
        def __init__(self, feature_count: int) -> None:
            super().__init__()
            self.embedding = torch.nn.EmbeddingBag(feature_count, CLASS_COUNT, mode="sum")
            self.bias = torch.nn.Parameter(torch.zeros(CLASS_COUNT))
            torch.nn.init.zeros_(self.embedding.weight)

        def forward(self, indices, offsets):
            return self.embedding(indices, offsets) + self.bias

    def batches(examples: list[Example], order: list[int]):
        for start in range(0, len(order), args.batch_size):
            selected = [examples[index] for index in order[start:start + args.batch_size]]
            lengths = [len(item.features) for item in selected]
            offsets = np.cumsum([0] + lengths[:-1], dtype=np.int64)
            nonempty = [item.features for item in selected if len(item.features)]
            flat = np.concatenate(nonempty) if nonempty else np.empty(0, dtype=np.int64)
            yield (
                torch.from_numpy(flat), torch.from_numpy(offsets),
                torch.tensor([item.label for item in selected]),
                torch.from_numpy(np.stack([item.teacher_logits for item in selected])),
            )

    def metrics(model: Student, examples: list[Example]) -> dict:
        predicted, teacher, truth = [], [], []
        kl_sum = 0.0
        model.eval()
        with torch.inference_mode():
            for indices, offsets, labels, teacher_logits in batches(
                examples, list(range(len(examples)))
            ):
                logits = model(indices, offsets)
                predicted.extend(logits.argmax(1).tolist())
                teacher.extend(teacher_logits.argmax(1).tolist())
                truth.extend(labels.tolist())
                kl_sum += float(functional.kl_div(
                    functional.log_softmax(logits, dim=1),
                    functional.softmax(teacher_logits, dim=1),
                    reduction="sum",
                ))
        return {
            "teacher_agreement": float(np.mean(np.equal(predicted, teacher))),
            "teacher_kl": kl_sum / len(examples),
            **classification_report(truth, predicted),
        }

    def loss_for(objective: str, temperature: float, logits, labels, teacher_logits):
        ground_truth = functional.cross_entropy(logits, labels)
        teacher_top1 = functional.cross_entropy(logits, teacher_logits.argmax(1))
        soft = functional.kl_div(
            functional.log_softmax(logits / temperature, dim=1),
            functional.softmax(teacher_logits / temperature, dim=1),
            reduction="batchmean",
        ) * temperature * temperature
        if objective == "ground_truth_ce_plus_soft_kd":
            return 0.25 * ground_truth + 0.75 * soft
        if objective == "teacher_top1_ce":
            return teacher_top1
        if objective == "soft_teacher_kl":
            return soft
        if objective == "teacher_top1_ce_plus_soft_kl":
            return 0.5 * teacher_top1 + 0.5 * soft
        if objective == "soft_kd_then_teacher_top1":
            return 0.25 * ground_truth + 0.75 * soft
        raise ValueError(objective)

    def fit(
        examples: dict[str, list[Example]], feature_count: int, objective: str,
        temperature: float, seed: int,
    ) -> dict:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.use_deterministic_algorithms(True)
        rng = random.Random(seed)
        model = Student(feature_count)
        optimizer = torch.optim.AdamW(
            model.parameters(), lr=args.learning_rate, weight_decay=1e-4
        )
        best_state = None
        best_validation = None
        best_key = None
        no_improvement = 0
        loss_history = []
        validation_history = []
        for epoch in range(1, args.max_epochs + 1):
            order = balanced_order(examples["train"], rng)
            model.train()
            loss_sum = 0.0
            for indices, offsets, labels, teacher_logits in batches(examples["train"], order):
                optimizer.zero_grad()
                logits = model(indices, offsets)
                loss = loss_for(objective, temperature, logits, labels, teacher_logits)
                loss.backward()
                optimizer.step()
                loss_sum += float(loss.detach()) * len(labels)
            train_loss = loss_sum / len(examples["train"])
            validation = metrics(model, examples["validation"])
            loss_history.append(train_loss)
            validation_history.append(validation["teacher_agreement"])
            # Agreement is the primary selector; KL and ground-truth accuracy only break ties.
            key = (validation["teacher_agreement"], -validation["teacher_kl"],
                   validation["accuracy"])
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

        # The staged objective gets a bounded low-LR top-1-only finishing pass.
        fine_tune_losses = []
        if objective == "soft_kd_then_teacher_top1":
            optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate * 0.1,
                                          weight_decay=1e-4)
            staged_best_state = {name: value.detach().clone()
                                 for name, value in model.state_dict().items()}
            staged_best_validation = best_validation
            staged_best_key = best_key
            for _ in range(5):
                order = balanced_order(examples["train"], rng)
                model.train()
                total = 0.0
                for indices, offsets, labels, teacher_logits in batches(examples["train"], order):
                    optimizer.zero_grad()
                    logits = model(indices, offsets)
                    loss = functional.cross_entropy(logits, teacher_logits.argmax(1))
                    loss.backward()
                    optimizer.step()
                    total += float(loss.detach()) * len(labels)
                fine_tune_losses.append(total / len(examples["train"]))
                validation = metrics(model, examples["validation"])
                key = (validation["teacher_agreement"], -validation["teacher_kl"],
                       validation["accuracy"])
                if key > staged_best_key:
                    staged_best_key = key
                    staged_best_validation = {**validation, "epoch": best_validation["epoch"],
                                              "fine_tune_epoch": len(fine_tune_losses)}
                    staged_best_state = {name: value.detach().clone()
                                         for name, value in model.state_dict().items()}
            model.load_state_dict(staged_best_state)
            best_validation = staged_best_validation

        return {
            "seed": seed,
            "selected_validation": best_validation,
            "epochs_ran": len(loss_history),
            "training_loss_first": loss_history[0],
            "training_loss_last": loss_history[-1],
            "training_loss_min": min(loss_history),
            "training_loss_history": loss_history,
            "validation_agreement_history": validation_history,
            "fine_tune_loss_history": fine_tune_losses,
            "train": metrics(model, examples["train"]),
            "validation": metrics(model, examples["validation"]),
            "development": metrics(model, examples["test"]),
        }

    configurations = []
    configuration_specs = []
    if args.phase == "diagnostic":
        representations = [("exact_train_vocabulary", "exact", len(vocabulary)),
                           ("fnv_8k", "hashed", 8192), ("fnv_16k", "hashed", 16384)]
        objectives = [("ground_truth_ce_plus_soft_kd", 2.0)]
    elif args.phase == "objectives":
        representations = [("fnv_8k", "hashed", 8192), ("fnv_16k", "hashed", 16384)]
        objectives = [("teacher_top1_ce", 1.0)]
        for objective in ("ground_truth_ce_plus_soft_kd", "soft_teacher_kl",
                          "teacher_top1_ce_plus_soft_kl",
                          "soft_kd_then_teacher_top1"):
            objectives.extend((objective, temperature) for temperature in (1.0, 2.0, 4.0))
    elif args.phase == "learning_curve":
        representations = []
        objectives = []
        if args.learning_curve_sizes[-1] != len(raw["train"]):
            raise ValueError("learning curve must end with the complete transfer set")
        if args.learning_curve_sizes[0] != 4900:
            raise ValueError("learning curve must begin with the Experiment C training set")
        existing = [row for row in raw["train"] if "recovery_remapped_from_student_split" not in row]
        additions = [row for row in raw["train"] if "recovery_remapped_from_student_split" in row]
        if len(existing) != 4900:
            raise RuntimeError("could not identify the original 4,900 training rows")
        random.Random(20260829 ^ 0x4C435552).shuffle(additions)
        nested_training = existing + additions
        for size in args.learning_curve_sizes:
            if size < 4900 or size > len(nested_training):
                raise ValueError(f"invalid learning-curve size {size}")
            selected_raw = {"train": nested_training[:size],
                            "validation": raw["validation"], "test": raw["test"]}
            configuration_specs.append(
                ("fnv_8k", "hashed", 8192, "teacher_top1_ce", 1.0, size, selected_raw)
            )
    else:
        representations = []
        objectives = []
        for representation, kind, width in (
            ("word_unigrams_8k", "word_unigram", 8192),
            ("word_bigrams_8k", "word_bigram", 8192),
            ("mixed_byte3_word1_word2_8k", "mixed", 8192),
            ("mixed_byte3_word1_word2_16k", "mixed", 16384),
            ("mixed_byte3_word1_word2_32k", "mixed", 32768),
            ("fnv_byte3_32k", "hashed", 32768),
        ):
            configuration_specs.append((representation, kind, width, "teacher_top1_ce",
                                        1.0, len(raw["train"]), raw))

    if not configuration_specs:
        for representation, kind, feature_count in representations:
            for objective, temperature in objectives:
                configuration_specs.append((representation, kind, feature_count, objective,
                                            temperature, len(raw["train"]), raw))

    cache = {}
    for (representation, kind, feature_count, objective, temperature, training_size,
         selected_raw) in configuration_specs:
        examples = cache.setdefault(
            (kind, feature_count, training_size), make_examples(kind, feature_count, selected_raw)
        )
        print(f"training n={training_size} {representation} {objective} T={temperature}", flush=True)
        runs = [fit(examples, feature_count, objective, temperature, seed)
                for seed in args.seeds]
        class_counts = Counter(item.label for item in examples["train"])
        configurations.append({
                "representation": representation,
                "feature_count": feature_count,
                "training_size": training_size,
                "training_examples_per_class": {
                    str(label): class_counts[index] for index, label in enumerate(
                        ("biology", "business", "chemistry", "computer science", "economics",
                         "engineering", "health", "history", "law", "math", "other",
                         "philosophy", "physics", "psychology"))
                },
                "objective": objective,
                "temperature": temperature,
                "parameter_count": feature_count * CLASS_COUNT + CLASS_COUNT,
                "estimated_int8_bpf_map_bytes": feature_count * CLASS_COUNT
                    + CLASS_COUNT * 4 + struct.calcsize("<8sIIIIId"),
                "seeds": runs,
                "aggregate": {
                    split: {
                        metric: mean_std([run[split][metric] for run in runs])
                        for metric in ("teacher_agreement", "accuracy", "macro_f1")
                    }
                    for split in ("train", "validation", "development")
                },
        })

    report = {
        "experiment": f"recovery linear {args.phase}",
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "teacher_targets_sha256": hashlib.sha256(args.teacher_targets.read_bytes()).hexdigest(),
        "sealed_final_used": False,
        "split_sizes": {split: len(split_rows) for split, split_rows in raw.items()},
        "exact_oracle": {
            "definition": "one collision-free ID per byte trigram observed in training; unseen validation/development trigrams ignored",
            "training_vocabulary_size": len(vocabulary),
        },
        "training": {
            "architecture": "linear EmbeddingBag plus bias",
            "optimizer": "AdamW",
            "learning_rate": args.learning_rate,
            "weight_decay": 1e-4,
            "max_epochs": args.max_epochs,
            "early_stopping_patience": args.patience,
            "selection": "validation teacher agreement, then teacher KL, then ground-truth accuracy",
            "sampling": "balanced minibatch sampling (uniform-class draws)",
            "batch_size": args.batch_size,
            "seeds": args.seeds,
        },
        "configurations": configurations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "configurations": [{
            "representation": item["representation"],
            "objective": item["objective"],
            "temperature": item["temperature"],
            "aggregate": item["aggregate"],
        } for item in configurations],
    }, indent=2))


if __name__ == "__main__":
    main()
