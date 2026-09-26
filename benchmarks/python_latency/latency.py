"""Pure scheduling and aggregation helpers for the latency client."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any


NS_PER_SECOND = 1_000_000_000
T_975_DF4 = 2.776


def scheduled_time_ns(start_ns: int, sequence: int, rate: float) -> int:
    """Return an absolute target without accumulating interval rounding error."""
    if sequence < 0:
        raise ValueError("sequence must be non-negative")
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("rate must be a positive finite number")
    return start_ns + int(sequence * NS_PER_SECOND / rate)


def worker_for(sequence: int, connections: int) -> int:
    if sequence < 0:
        raise ValueError("sequence must be non-negative")
    if connections < 1:
        raise ValueError("connections must be positive")
    return sequence % connections


def percentile(values: Iterable[float], quantile: float) -> float | None:
    """Linear interpolation matching the common type-7 sample percentile."""
    samples = sorted(values)
    if not samples:
        return None
    if not 0 <= quantile <= 100:
        raise ValueError("quantile must be between 0 and 100")
    position = (len(samples) - 1) * quantile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return samples[lower]
    return samples[lower] + (samples[upper] - samples[lower]) * (position - lower)


def mean(values: Iterable[float]) -> float | None:
    samples = list(values)
    return sum(samples) / len(samples) if samples else None


def mean_ci95_five_trials(values: Iterable[float]) -> tuple[float | None, float | None]:
    samples = list(values)
    if not samples:
        return None, None
    average = sum(samples) / len(samples)
    if len(samples) != 5:
        return average, None
    variance = sum((value - average) ** 2 for value in samples) / 4
    return average, T_975_DF4 * math.sqrt(variance) / math.sqrt(5)


@dataclass(slots=True)
class RequestResult:
    trial: int
    system: str
    requested_rate: float
    worker_id: int
    sequence: int
    prompt_index: int
    worker_busy_when_scheduled: bool
    scheduled_ns: int
    request_start_ns: int
    response_headers_ns: int | None
    response_complete_ns: int | None
    actual_latency_us: float | None
    scheduling_delay_us: float
    time_to_headers_us: float | None
    response_body_us: float | None
    http_status: int | None
    backend_marker: str | None
    error_type: str | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_requests(
    results: list[RequestResult], *, duration_seconds: float, late_threshold_us: float = 0.0
) -> dict[str, Any]:
    completed = [
        row for row in results
        if row.response_complete_ns is not None and row.error_type is None
    ]
    latencies = [row.actual_latency_us for row in completed if row.actual_latency_us is not None]
    delays = [row.scheduling_delay_us for row in results]
    starts = sorted(row.request_start_ns for row in results)
    intervals = [(right - left) / 1_000 for left, right in zip(starts, starts[1:])]

    def distribution(values: list[float]) -> dict[str, float | None]:
        return {
            "mean": mean(values),
            "p50": percentile(values, 50),
            "p95": percentile(values, 95),
            "p99": percentile(values, 99),
            "max": max(values) if values else None,
        }

    return {
        "requested_rps": results[0].requested_rate if results else None,
        "achieved_rps": len(completed) / duration_seconds,
        "scheduled_requests": len(results),
        "completed_requests": len(completed),
        "actual_latency_us": distribution(latencies),
        "scheduling_delay_us": distribution(delays),
        "interarrival_us": {
            "mean": mean(intervals),
            "median": percentile(intervals, 50),
            "p5": percentile(intervals, 5),
            "p95": percentile(intervals, 95),
        },
        "late_requests": sum(delay > late_threshold_us for delay in delays),
        "requests_scheduled_while_worker_busy": sum(
            row.worker_busy_when_scheduled for row in results
        ),
        "http_errors": sum(
            row.http_status is not None and row.http_status >= 400 for row in results
        ),
        "connection_errors": sum(row.error_type == "connection" for row in results),
        "timeout_errors": sum(row.error_type == "timeout" for row in results),
        "other_errors": sum(row.error_type == "other" for row in results),
    }
