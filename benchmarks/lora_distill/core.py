"""Shared, dependency-light semantics for the bounded FNV student."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import numpy as np

LABELS = (
    "biology", "business", "chemistry", "computer science", "economics",
    "engineering", "health", "history", "law", "math", "other",
    "philosophy", "physics", "psychology",
)
LABEL_TO_ID = {label: index for index, label in enumerate(LABELS)}
FEATURE_COUNT = 4096
CLASS_COUNT = 14
PROMPT_BYTE_LIMIT = 16_384
FNV_OFFSET = 2_166_136_261
FNV_PRIME = 16_777_619
MODEL_MAGIC = b"XSRFNV14"
MODEL_VERSION = 1


def normalize_bytes(prompt: str, limit: int = PROMPT_BYTE_LIMIT) -> bytes:
    """UTF-8 encode, fold only ASCII A-Z, then apply the kernel byte bound."""
    raw = prompt.encode("utf-8")[:limit]
    return bytes(value + 32 if 65 <= value <= 90 else value for value in raw)


def normalized_prompt_key(prompt: str) -> str:
    """Stable cross-split dedupe key; deliberately matches student semantics."""
    return hashlib.sha256(normalize_bytes(prompt, limit=2**31 - 1)).hexdigest()


def fnv1a_trigram(trigram: Sequence[int], feature_count: int = FEATURE_COUNT) -> int:
    if feature_count <= 0 or feature_count & (feature_count - 1):
        raise ValueError("feature count must be a positive power of two")
    value = FNV_OFFSET
    for byte in trigram:
        value ^= int(byte)
        value = (value * FNV_PRIME) & 0xFFFFFFFF
    return value & (feature_count - 1)


def feature_indices(
    prompt: str, limit: int = PROMPT_BYTE_LIMIT, feature_count: int = FEATURE_COUNT,
) -> np.ndarray:
    data = normalize_bytes(prompt, limit)
    return np.fromiter(
        (fnv1a_trigram(data[i : i + 3], feature_count)
         for i in range(max(0, len(data) - 2))),
        dtype=np.int64,
    )


def dense_counts(prompt: str, limit: int = PROMPT_BYTE_LIMIT) -> np.ndarray:
    return np.bincount(feature_indices(prompt, limit), minlength=FEATURE_COUNT)


def stable_softmax(logits: Sequence[float], temperature: float = 1.0) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float64) / temperature
    values -= values.max()
    values = np.exp(values)
    return values / values.sum()


def float_scores(prompt: str, weights: np.ndarray, bias: np.ndarray) -> np.ndarray:
    indices = feature_indices(prompt)
    return bias + (weights[:, indices].sum(axis=1) if len(indices) else 0)


def integer_scores(prompt: str, weights: np.ndarray, bias: np.ndarray) -> np.ndarray:
    indices = feature_indices(prompt)
    scores = np.asarray(bias, dtype=np.int64).copy()
    if len(indices):
        scores += np.asarray(weights[:, indices], dtype=np.int64).sum(axis=1)
    return scores


def predict(scores: Sequence[float]) -> int:
    """First maximum, matching Python/numpy and the kernel's strict > tie-break."""
    return int(np.argmax(scores))


@dataclass(frozen=True)
class QuantizedModel:
    weights: np.ndarray
    bias: np.ndarray
    scale: float


def quantize_global(weights: np.ndarray, bias: np.ndarray, bits: int = 8) -> QuantizedModel:
    if bits not in (8, 16):
        raise ValueError("only int8 and int16 diagnostics are supported")
    bound = (1 << (bits - 1)) - 1
    maximum = float(np.max(np.abs(weights)))
    if not math.isfinite(maximum) or maximum <= 0:
        raise ValueError("weights must contain a finite non-zero value")
    scale = bound / maximum
    dtype = np.int8 if bits == 8 else np.int16
    quantized_weights = np.clip(np.rint(weights * scale), -bound, bound).astype(dtype)
    scaled_bias = np.rint(bias * scale)
    if np.max(np.abs(scaled_bias)) > np.iinfo(np.int32).max:
        raise OverflowError("quantized bias does not fit signed int32")
    quantized_bias = scaled_bias.astype(np.int32)
    return QuantizedModel(quantized_weights, quantized_bias, scale)


def overflow_bound(bias: Sequence[int], prompt_limit: int = PROMPT_BYTE_LIMIT, weight_bound: int = 127) -> int:
    return int(np.max(np.abs(bias))) + max(0, prompt_limit - 2) * weight_bound


def write_kernel_model(path: Path, model: QuantizedModel) -> None:
    weights = np.asarray(model.weights, dtype=np.int8)
    bias = np.asarray(model.bias, dtype=np.int32)
    if weights.shape != (CLASS_COUNT, FEATURE_COUNT) or bias.shape != (CLASS_COUNT,):
        raise ValueError("expected weights [14,4096] and bias [14]")
    bound = overflow_bound(bias)
    if bound > np.iinfo(np.int32).max:
        raise OverflowError(f"signed int32 score bound exceeded: {bound}")
    header = struct.pack("<8sIIIIId", MODEL_MAGIC, MODEL_VERSION, CLASS_COUNT,
                         FEATURE_COUNT, PROMPT_BYTE_LIMIT, bound, model.scale)
    # Kernel map values are one 14-weight vector per bucket.
    path.write_bytes(header + bias.astype("<i4").tobytes() + weights.T.tobytes())


def read_kernel_model(path: Path) -> QuantizedModel:
    data = path.read_bytes()
    header_size = struct.calcsize("<8sIIIIId")
    magic, version, classes, features, prompt_limit, bound, scale = struct.unpack(
        "<8sIIIIId", data[:header_size]
    )
    if (magic, version, classes, features, prompt_limit) != (
        MODEL_MAGIC, MODEL_VERSION, CLASS_COUNT, FEATURE_COUNT, PROMPT_BYTE_LIMIT
    ):
        raise ValueError("incompatible kernel model header")
    expected = header_size + CLASS_COUNT * 4 + FEATURE_COUNT * CLASS_COUNT
    if len(data) != expected:
        raise ValueError(f"bad model size {len(data)} (expected {expected})")
    offset = header_size
    bias = np.frombuffer(data[offset : offset + CLASS_COUNT * 4], dtype="<i4").copy()
    weights = np.frombuffer(data[offset + CLASS_COUNT * 4 :], dtype=np.int8).reshape(
        FEATURE_COUNT, CLASS_COUNT
    ).T.copy()
    if overflow_bound(bias) != bound:
        raise ValueError("model overflow proof does not match payload")
    return QuantizedModel(weights, bias, scale)


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: {exc}") from exc


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
