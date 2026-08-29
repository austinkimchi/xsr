from pathlib import Path

import numpy as np

from core import (CLASS_COUNT, FEATURE_COUNT, PROMPT_BYTE_LIMIT, QuantizedModel,
                  feature_indices, fnv1a_trigram, integer_scores, normalize_bytes,
                  overflow_bound, read_kernel_model, write_kernel_model)


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
