"""Utilities shared by the repeated-trial benchmark analysis notebook.

The benchmark runner deliberately stores invalid trial records without metrics.
These helpers keep those records visible while ensuring they cannot leak into a
paper comparison or an aggregate statistic.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


SATURATION_CONFIGURATION = re.compile(r"^concurrency-(\d+)$")
FIXED_RATE_CONFIGURATION = re.compile(r"^rate-(\d+)_concurrency-(\d+)$")
LATENCY_METRICS = {
    "average_latency_us",
    "p50_latency_us",
    "p95_latency_us",
    "p99_latency_us",
}
REQUIRED_SYSTEMS = (
    "Direct backend",
    "Envoy only",
    "XSR (SK_SKB/SOCKMAP)",
    "VSR (Envoy ExtProc)",
)


def parse_configuration(configuration: str) -> dict[str, int | None]:
    """Parse a hardened benchmark configuration name."""
    saturation = SATURATION_CONFIGURATION.fullmatch(configuration)
    if saturation:
        return {"concurrency": int(saturation.group(1)), "offered_rate_rps": None}
    fixed_rate = FIXED_RATE_CONFIGURATION.fullmatch(configuration)
    if fixed_rate:
        return {"concurrency": int(fixed_rate.group(2)), "offered_rate_rps": int(fixed_rate.group(1))}
    raise ValueError(
        f"unsupported configuration {configuration!r}; expected concurrency-<N> "
        "or rate-<R>_concurrency-<N>"
    )


def metric_value_ms(metric: str, value: float | int | None) -> float | None:
    """Convert microsecond latency metrics to milliseconds exactly once."""
    if value is None:
        return None
    return float(value) / 1_000.0 if metric in LATENCY_METRICS else float(value)


def flatten_summary(summary: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    """Turn summary.json aggregates into one tidy row per metric and system."""
    rows: list[dict[str, Any]] = []
    for result in summary.get("results", []):
        parsed = parse_configuration(str(result["configuration"]))
        for metric, values in result.get("metrics", {}).items():
            row = {
                "run_id": run_id,
                "mode": result.get("mode"),
                "configuration": result["configuration"],
                "concurrency": parsed["concurrency"],
                "offered_rate_rps": parsed["offered_rate_rps"],
                "system": result.get("system"),
                "topology": result.get("topology"),
                "valid_trial_count": int(result.get("valid_trial_count", 0)),
                "failed_trial_count": int(result.get("failed_trial_count", 0)),
                "metric": metric,
            }
            for statistic in ("mean", "stdev", "median", "minimum", "maximum", "ci95"):
                row[statistic] = metric_value_ms(metric, values.get(statistic))
            rows.append(row)
    return rows


def load_trial_records(run_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """Load every raw result artifact, retaining invalid records and reasons."""
    paths = sorted((run_dir / "raw").glob("**/result.json"))
    if not paths:
        raise FileNotFoundError(f"no raw/**/result.json artifacts under {run_dir}")
    records: list[dict[str, Any]] = []
    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        parsed = parse_configuration(str(record["configuration"]))
        item = dict(record)
        item.update({
            "run_id": run_id,
            "concurrency": parsed["concurrency"],
            "offered_rate_rps": parsed["offered_rate_rps"],
            "result_path": str(path),
            "failure_reasons": list(record.get("failure_reasons") or []),
        })
        for metric, value in list((record.get("metrics") or {}).items()):
            item[metric] = metric_value_ms(metric, value)
        records.append(item)
    return records


def exclusion_reasons(
    summary_rows: Iterable[dict[str, Any]],
    trial_count: int,
    required_systems: Iterable[str] = REQUIRED_SYSTEMS,
    paper_max_concurrency: int = 256,
    required_metrics: Iterable[str] = ("throughput_rps",),
) -> dict[str, list[str]]:
    """Explain all configurations excluded from four-path paper figures."""
    required = tuple(required_systems)
    required_metrics = tuple(required_metrics)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in summary_rows:
        grouped[str(row["configuration"])].append(row)
    exclusions: dict[str, list[str]] = {}
    for configuration, rows in grouped.items():
        reasons: list[str] = []
        concurrency = rows[0]["concurrency"]
        if concurrency is None or concurrency > paper_max_concurrency:
            reasons.append(f"concurrency exceeds paper maximum ({paper_max_concurrency})")
        by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_system[str(row["system"])].append(row)
        for system in required:
            system_rows = by_system.get(system, [])
            if not system_rows:
                reasons.append(f"missing required system: {system}")
                continue
            trial_row = next((row for row in system_rows if row["metric"] == "throughput_rps"), system_rows[0])
            if trial_row["valid_trial_count"] != trial_count or trial_row["failed_trial_count"] != 0:
                reasons.append(
                    f"{system}: valid={trial_row['valid_trial_count']}/{trial_count}, "
                    f"failed={trial_row['failed_trial_count']}"
                )
            present_metrics = {row["metric"] for row in system_rows}
            for metric in required_metrics:
                if metric not in present_metrics:
                    reasons.append(f"{system}: missing required metric: {metric}")
        if reasons:
            exclusions[configuration] = reasons
    return exclusions


def paper_valid_configurations(
    summary_rows: Iterable[dict[str, Any]],
    trial_count: int,
    required_systems: Iterable[str] = REQUIRED_SYSTEMS,
    paper_max_concurrency: int = 256,
    required_metrics: Iterable[str] = ("throughput_rps",),
) -> set[str]:
    summary_rows = list(summary_rows)
    exclusions = exclusion_reasons(summary_rows, trial_count, required_systems, paper_max_concurrency, required_metrics)
    configurations = {str(row["configuration"]) for row in summary_rows}
    return configurations - set(exclusions)


def paired_ratios(
    records: Iterable[dict[str, Any]], numerator: str, denominator: str, metric: str,
    allowed_configurations: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Compute ratios from valid records paired by configuration and trial."""
    allowed = set(allowed_configurations) if allowed_configurations is not None else None
    pairs: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for record in records:
        configuration = str(record.get("configuration"))
        if allowed is not None and configuration not in allowed:
            continue
        if record.get("valid") and record.get(metric) is not None:
            pairs[(configuration, int(record["trial"]))][str(record["system"])] = record
    values: list[dict[str, Any]] = []
    for (configuration, trial), systems in sorted(pairs.items()):
        top, bottom = systems.get(numerator), systems.get(denominator)
        if top is None or bottom is None or not bottom[metric]:
            continue
        values.append({
            "configuration": configuration,
            "concurrency": top["concurrency"],
            "offered_rate_rps": top["offered_rate_rps"],
            "trial": trial,
            "numerator": numerator,
            "denominator": denominator,
            "metric": metric,
            "ratio": float(top[metric]) / float(bottom[metric]),
        })
    return values


def ratio_statistics(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate independently paired ratios with a between-trial 95% CI."""
    groups: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in rows:
        groups[(row["configuration"], row["concurrency"], row["offered_rate_rps"], row["numerator"], row["denominator"], row["metric"])].append(float(row["ratio"]))
    output: list[dict[str, Any]] = []
    for key, values in sorted(groups.items()):
        stdev = statistics.stdev(values) if len(values) > 1 else 0.0
        output.append({
            "configuration": key[0], "concurrency": key[1], "offered_rate_rps": key[2],
            "numerator": key[3], "denominator": key[4], "metric": key[5],
            "trial_count": len(values), "mean": statistics.mean(values), "stdev": stdev,
            "ci95": 1.96 * stdev / math.sqrt(len(values)) if len(values) > 1 else 0.0,
        })
    return output


def parse_wrk_output(text: str) -> dict[str, float | int | None]:
    """Parse values usable only for a marked diagnostic from wrk output."""
    def number(pattern: str) -> float | None:
        match = re.search(pattern, text, re.MULTILINE)
        return float(match.group(1)) if match else None
    def latency(pattern: str) -> float | None:
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            return None
        value, unit = float(match.group(1)), match.group(2)
        return value * {"us": 0.001, "ms": 1.0, "s": 1000.0}[unit]
    timeout = number(r"Socket errors:.*?timeout\s+(\d+)")
    non_success = number(r"Non-2xx or 3xx responses:\s*(\d+)")
    return {
        "throughput_rps": number(r"^Requests/sec:\s*([0-9.]+)"),
        "average_latency_ms": latency(r"^\s*Latency\s+([0-9.]+)(us|ms|s)"),
        "maximum_latency_ms": latency(r"^\s*Latency\s+\S+\s+\S+\s+([0-9.]+)(us|ms|s)"),
        "p50_latency_ms": number(r"p50=([0-9.]+)us"),
        "p95_latency_ms": number(r"p95=([0-9.]+)us"),
        "p99_latency_ms": number(r"p99=([0-9.]+)us"),
        "timeout_count": int(timeout) if timeout is not None else None,
        "non_success_count": int(non_success) if non_success is not None else None,
    }


def diagnostic_rows(run_dir: Path, records: Iterable[dict[str, Any]], concurrency: int = 512) -> list[dict[str, Any]]:
    """Attach parseable raw output to c=512 records without normalizing it."""
    output: list[dict[str, Any]] = []
    for record in records:
        if record.get("mode") != "saturation" or record.get("concurrency") != concurrency:
            continue
        raw_path = Path(str(record.get("raw_output", "")))
        if not raw_path.is_file():
            raw_path = Path(str(record["result_path"])).with_name("wrk.txt")
        parsed = parse_wrk_output(raw_path.read_text(encoding="utf-8", errors="replace")) if raw_path.is_file() else {}
        for percentile in ("p50_latency_ms", "p95_latency_ms", "p99_latency_ms"):
            if parsed.get(percentile) is not None:
                parsed[percentile] = float(parsed[percentile]) / 1_000.0
        invalid_path = raw_path.with_name("invalid.txt")
        reasons = list(record.get("failure_reasons") or [])
        if invalid_path.is_file():
            reasons.extend(line.strip() for line in invalid_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
        row = dict(record) | parsed
        row.update({
            "failure_reasons": sorted(set(reasons)), "raw_file_path": str(raw_path),
            "invalid_file_path": str(invalid_path) if invalid_path.is_file() else None,
            "diagnostic_only": True,
        })
        if row.get("system") == "VSR (Envoy ExtProc)" and row.get("throughput_rps") and row.get("average_latency_ms"):
            row["estimated_inflight_requests"] = float(row["throughput_rps"]) * float(row["average_latency_ms"]) / 1_000.0
        else:
            row["estimated_inflight_requests"] = None
        output.append(row)
    return output
