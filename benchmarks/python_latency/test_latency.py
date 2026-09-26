from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

from benchmarks.python_latency.client import CSV_FIELDS, extract_backend, load_prompts
from benchmarks.python_latency.latency import (
    RequestResult,
    mean_ci95_five_trials,
    percentile,
    scheduled_time_ns,
    summarize_requests,
    worker_for,
)


def result(**overrides: object) -> RequestResult:
    values = {
        "trial": 1,
        "system": "direct",
        "requested_rate": 5.0,
        "worker_id": 0,
        "sequence": 0,
        "prompt_index": 0,
        "worker_busy_when_scheduled": False,
        "scheduled_ns": 1_000_000,
        "request_start_ns": 1_005_000,
        "response_headers_ns": 1_010_000,
        "response_complete_ns": 1_015_000,
        "actual_latency_us": 10.0,
        "scheduling_delay_us": 5.0,
        "time_to_headers_us": 5.0,
        "response_body_us": 5.0,
        "http_status": 200,
        "backend_marker": "coding",
        "error_type": None,
        "error": None,
    }
    values.update(overrides)
    return RequestResult(**values)  # type: ignore[arg-type]


def test_absolute_schedule_does_not_accumulate_rounding() -> None:
    start = 8_000_000_000
    assert scheduled_time_ns(start, 0, 25) == start
    assert scheduled_time_ns(start, 1, 25) == start + 40_000_000
    assert scheduled_time_ns(start, 100, 3) == start + int(100e9 / 3)


def test_round_robin_assignment() -> None:
    assert [worker_for(index, 4) for index in range(8)] == [0, 1, 2, 3, 0, 1, 2, 3]


def test_latency_delay_and_percentile_aggregation() -> None:
    rows = [
        result(sequence=index, actual_latency_us=value, scheduling_delay_us=value / 10)
        for index, value in enumerate([10.0, 20.0, 30.0, 40.0, 50.0])
    ]
    summary = summarize_requests(rows, duration_seconds=1)
    assert summary["actual_latency_us"]["mean"] == 30
    assert summary["actual_latency_us"]["p50"] == 30
    assert summary["scheduling_delay_us"]["p95"] == pytest.approx(4.8)
    assert percentile([1, 2, 3, 4], 95) == pytest.approx(3.85)
    assert mean_ci95_five_trials([1, 2, 3, 4, 5]) == pytest.approx(
        (3, 1.9629284245738559)
    )


def test_prompt_loading_strips_annotation_and_cycles() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "prompts.jsonl"
        path.write_text(
            '{"model":"MoM","messages":[],"x_expected_route":"coding"}\n'
            '{"model":"MoM","messages":[{"content":"two"}]}\n',
            encoding="utf-8",
        )
        prompts = load_prompts(path)
    assert len(prompts) == 2
    assert "x_expected_route" not in json.loads(prompts[0])
    assert [json.loads(prompts[index % len(prompts)])["messages"] for index in range(3)] == [
        [], [{"content": "two"}], []
    ]


def test_result_serialization_has_stable_csv_fields() -> None:
    row = result().to_dict()
    assert list(row) == CSV_FIELDS
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "row.csv"
        with path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerow(row)
        assert next(csv.DictReader(path.open(encoding="utf-8")))["backend_marker"] == "coding"


def test_error_handling_counts_categories_and_excludes_latency() -> None:
    rows = [
        result(),
        result(
            sequence=1,
            response_headers_ns=None,
            response_complete_ns=None,
            actual_latency_us=None,
            http_status=None,
            error_type="timeout",
            error="TimeoutError",
        ),
        result(sequence=2, http_status=503),
    ]
    summary = summarize_requests(rows, duration_seconds=1)
    assert summary["completed_requests"] == 2
    assert summary["timeout_errors"] == 1
    assert summary["http_errors"] == 1
    assert summary["actual_latency_us"]["mean"] == 10


def test_backend_marker_extraction() -> None:
    assert extract_backend(b'{"backend":"math"}') == "math"
    assert extract_backend(b'{"model":"writing"}') == "writing"
    assert extract_backend(b"not-json") is None
