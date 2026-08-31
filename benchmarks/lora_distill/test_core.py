import random
from pathlib import Path

import numpy as np

from core import (CLASS_COUNT, DEPLOYMENT_FEATURE_COUNT, FEATURE_COUNT,
                  PROMPT_BYTE_LIMIT, QuantizedModel, float_scores,
                  feature_indices, fnv1a_trigram, integer_scores, normalize_bytes,
                  overflow_bound, read_deployment_model, read_kernel_model,
                  write_kernel_model)
from overfit_balanced import balanced_subset
from rebalance_experiment import balanced_order
from recovery_linear_experiment import (exact_features, exact_training_vocabulary,
                                        word_features, word_tokens)
from train_students import Example


def test_normalization_is_ascii_only_and_bounded():
    assert normalize_bytes("AbCé") == b"abc\xc3\xa9"
    assert len(normalize_bytes("A" * (PROMPT_BYTE_LIMIT + 4))) == PROMPT_BYTE_LIMIT


def test_fnv_known_value_and_consecutive_trigrams():
    assert fnv1a_trigram(b"abc") == 2315
    assert feature_indices("ABCD").tolist() == [fnv1a_trigram(b"abc"), fnv1a_trigram(b"bcd")]
    assert fnv1a_trigram(b"abc", 8192) == 2315
    assert fnv1a_trigram(b"aaa") == 866
    assert fnv1a_trigram(b"aaa", 8192) == 4962
    assert feature_indices("AAA", feature_count=8192).tolist() == [4962]


def test_kernel_model_round_trip_and_integer_scores(tmp_path: Path):
    weights = np.zeros((CLASS_COUNT, DEPLOYMENT_FEATURE_COUNT), dtype=np.int8)
    weights[3, fnv1a_trigram(b"abc", DEPLOYMENT_FEATURE_COUNT)] = 7
    bias = np.arange(CLASS_COUNT, dtype=np.int32)
    model = QuantizedModel(weights, bias, 12.5)
    path = tmp_path / "model.xsrf"
    write_kernel_model(path, model)
    loaded = read_kernel_model(path)
    assert loaded.scale == model.scale
    assert np.array_equal(loaded.weights, weights)
    assert integer_scores("ABC", loaded.weights, loaded.bias)[3] == bias[3] + 7
    assert overflow_bound(bias) < np.iinfo(np.int32).max


def test_deployment_width_is_inferred_and_shared_with_c():
    weights = np.zeros((CLASS_COUNT, DEPLOYMENT_FEATURE_COUNT), dtype=np.float32)
    bucket = fnv1a_trigram(b"aaa", DEPLOYMENT_FEATURE_COUNT)
    weights[4, bucket] = 2.5
    bias = np.arange(CLASS_COUNT, dtype=np.float32)
    assert float_scores("AAA", weights, bias)[4] == bias[4] + 2.5

    format_header = Path(__file__).parents[2] / "include" / "xsr" / "distill_model_format.h"
    contents = format_header.read_text()
    assert f"#define XSR_DISTILL_BUCKETS {DEPLOYMENT_FEATURE_COUNT}" in contents
    assert f"#define XSR_DISTILL_CLASSES {CLASS_COUNT}" in contents
    assert f"#define XSR_DISTILL_PROMPT_BYTES {PROMPT_BYTE_LIMIT}" in contents
    assert '#define XSR_DISTILL_MODEL_MAGIC "XSRFNV14"' in contents
    assert "#define XSR_DISTILL_MODEL_VERSION 1" in contents


def test_historical_4k_format_round_trips_but_deployment_rejects_it(tmp_path: Path):
    model = QuantizedModel(
        np.zeros((CLASS_COUNT, FEATURE_COUNT), dtype=np.int8),
        np.zeros(CLASS_COUNT, dtype=np.int32),
        1.0,
    )
    path = tmp_path / "legacy-4k.xsrf"
    write_kernel_model(path, model)
    assert read_kernel_model(path).weights.shape == (CLASS_COUNT, FEATURE_COUNT)
    try:
        read_deployment_model(path)
    except ValueError as error:
        assert "model has 4096 buckets; required 8192" in str(error)
    else:
        raise AssertionError("historical 4K model unexpectedly accepted for deployment")


def test_bpf_distill_path_owns_feature_generation_and_state():
    source = (
        Path(__file__).parents[2]
        / "bpf"
        / "stages"
        / "signals"
        / "xdp_distill_classifier.bpf.h"
    ).read_text()
    assert "xdp_distill_ascii_lower(value)" in source
    assert "hash = 2166136261U" in source
    assert "bpf_map_lookup_elem(&xdp_distill_weights, &bucket)" in source
    assert "state->score[c] += weights->weight[c]" in source
    assert "jaccard" not in source
    assert "bm25" not in source


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


def test_recovery_exact_features_are_collision_free_and_ignore_unseen():
    vocabulary = exact_training_vocabulary([{"prompt": "ABCD"}])
    assert len(vocabulary) == 2
    assert exact_features("abcd", vocabulary).tolist() == [vocabulary[b"abc"], vocabulary[b"bcd"]]
    assert exact_features("xyz", vocabulary).tolist() == []


def test_recovery_word_features_are_bounded_and_namespaced():
    assert word_tokens("Hello, W0RLD! café") == [b"hello", b"w0rld", b"caf"]
    unigram = word_features("Hello world", 8192, "word_unigram")
    bigram = word_features("Hello world", 8192, "word_bigram")
    mixed = word_features("Hello world", 8192, "mixed")
    assert len(unigram) == 2
    assert len(bigram) == 1
    assert len(mixed) == len(feature_indices("Hello world", feature_count=8192)) + 3
    assert np.all((0 <= mixed) & (mixed < 8192))
