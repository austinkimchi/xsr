import random
from pathlib import Path

import numpy as np

from core import (CLASS_COUNT, FEATURE_COUNT, PROMPT_BYTE_LIMIT, QuantizedModel,
                  feature_indices, fnv1a_trigram, integer_scores, normalize_bytes,
                  overflow_bound, read_kernel_model, write_kernel_model)
from overfit_balanced import balanced_subset
from rebalance_experiment import balanced_order
from train_students import Example


def test_normalization_is_ascii_only_and_bounded():
    assert normalize_bytes("AbCé") == b"abc\xc3\xa9"
    assert len(normalize_bytes("A" * (PROMPT_BYTE_LIMIT + 4))) == PROMPT_BYTE_LIMIT


def test_fnv_known_value_and_consecutive_trigrams():
    assert fnv1a_trigram(b"abc") == 2315
    assert feature_indices("ABCD").tolist() == [fnv1a_trigram(b"abc"), fnv1a_trigram(b"bcd")]


def test_kernel_model_round_trip_and_integer_scores(tmp_path: Path):
    weights = np.zeros((CLASS_COUNT, FEATURE_COUNT), dtype=np.int8)
    weights[3, fnv1a_trigram(b"abc")] = 7
    bias = np.arange(CLASS_COUNT, dtype=np.int32)
    model = QuantizedModel(weights, bias, 12.5)
    path = tmp_path / "model.xsrf"
    write_kernel_model(path, model)
    loaded = read_kernel_model(path)
    assert loaded.scale == model.scale
    assert np.array_equal(loaded.weights, weights)
    assert integer_scores("ABC", loaded.weights, loaded.bias)[3] == bias[3] + 7
    assert overflow_bound(bias) < np.iinfo(np.int32).max


def test_balanced_overfit_subset_is_deterministic_and_train_only():
    rows = []
    for label_index, label in enumerate(("biology", "business")):
        for row_index in range(4):
            rows.append({
                "student_split": "validation" if row_index == 3 else "train",
                "ground_truth_class": label,
                "prompt": f"{label_index}-{row_index}",
            })
    for label in (
        "chemistry", "computer science", "economics", "engineering", "health",
        "history", "law", "math", "other", "philosophy", "physics", "psychology",
    ):
        rows.extend({
            "student_split": "train",
            "ground_truth_class": label,
            "prompt": f"{label}-{row_index}",
        } for row_index in range(3))

    first = balanced_subset(rows, per_class=2, seed=7)
    second = balanced_subset(rows, per_class=2, seed=7)
    assert first == second
    assert len(first) == 28
    assert all(row["student_split"] == "train" for row in first)
    assert {label: sum(row["ground_truth_class"] == label for row in first)
            for label in ("biology", "business")} == {"biology": 2, "business": 2}


def test_balanced_training_order_draws_each_class_uniformly():
    rows = [Example(np.array([label]), label, np.zeros(CLASS_COUNT))
            for label in range(CLASS_COUNT)]
    rows.extend(Example(np.array([99]), 10, np.zeros(CLASS_COUNT)) for _ in range(13))
    first = balanced_order(rows, random.Random(9))
    second = balanced_order(rows, random.Random(9))
    labels = [rows[index].label for index in first]
    assert first == second
    assert len(first) == len(rows)
    assert set(labels[:CLASS_COUNT]) == set(range(CLASS_COUNT))
    counts = np.bincount(labels, minlength=CLASS_COUNT)
    assert counts.max() - counts.min() <= 1
