#!/usr/bin/env python3
"""Capture and summarize compile-time-gated VSR component counters."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


STAGES = (
    "request_fast_extract",
    "request_full_parse",
    "bm25_native",
    "decision_policy",
    "route_reply_build",
    "extproc_send",
    "request_body_total",
)
STACKED_COMPONENTS = (
    "request_parsing",
    "bm25_native",
    "decision_policy",
    "route_reply_build",
    "extproc_send",
)
METRICS = {
    "vsr_component_profile_events_total": "count",
    "vsr_component_profile_duration_nanoseconds_total": "total_ns",
}
SAMPLE_RE = re.compile(
    r'^(?P<metric>vsr_component_profile_(?:events|duration_nanoseconds)_total)'
    r'\{stage="(?P<stage>[^"]+)"\}\s+(?P<value>\S+)(?:\s+\d+)?$'
)


def _parse_nonnegative_integer(raw: str) -> int:
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError(f"invalid Prometheus value: {raw!r}") from error
    if not value.is_finite() or value < 0 or value != value.to_integral_value():
        raise ValueError(f"profiling counter is not a nonnegative integer: {raw!r}")
    return int(value)


def parse_snapshot(raw: str) -> dict[str, dict[str, int]]:
    values = {stage: {} for stage in STAGES}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        match = SAMPLE_RE.match(line)
        if not match:
            if line.startswith("vsr_component_profile_"):
                raise ValueError(f"malformed component-profile sample: {line!r}")
            continue
        stage = match.group("stage")
        if stage not in values:
            raise ValueError(f"unexpected component-profile stage: {stage!r}")
        field = METRICS[match.group("metric")]
        if field in values[stage]:
            raise ValueError(f"duplicate {field} sample for stage {stage!r}")
        values[stage][field] = _parse_nonnegative_integer(match.group("value"))

    for stage in STAGES:
        missing = {"count", "total_ns"} - values[stage].keys()
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"stage {stage!r} is missing: {names}")
    return values


def summarize_snapshots(
    before_raw: str,
    after_raw: str,
    expected_completed: int | None = None,
) -> dict[str, object]:
    before = parse_snapshot(before_raw)
    after = parse_snapshot(after_raw)
    stages: dict[str, dict[str, int | float]] = {}

    for stage in STAGES:
        count = after[stage]["count"] - before[stage]["count"]
        total_ns = after[stage]["total_ns"] - before[stage]["total_ns"]
        if count < 0 or total_ns < 0:
            raise RuntimeError(f"component counters decreased for stage {stage!r}")
        stages[stage] = {
            "count": count,
            "total_ns": total_ns,
            "mean_ns": total_ns / count if count else 0.0,
            "mean_us": total_ns / count / 1000.0 if count else 0.0,
        }

    counts = {int(stages[stage]["count"]) for stage in STAGES}
    if len(counts) != 1:
        rendered = ", ".join(
            f"{stage}={stages[stage]['count']}" for stage in STAGES
        )
        raise RuntimeError(f"BM25 component event counts differ: {rendered}")
    completed = int(stages["request_body_total"]["count"])
    if completed <= 0:
        raise RuntimeError("no completed profiled BM25 requests")
    if expected_completed is not None and completed != expected_completed:
        raise RuntimeError(
            f"profiled request count {completed} does not match "
            f"expected valid request count {expected_completed}"
        )

    parsing_total_ns = int(stages["request_fast_extract"]["total_ns"]) + int(
        stages["request_full_parse"]["total_ns"]
    )
    components = {
        "request_parsing": {
            "count": completed,
            "total_ns": parsing_total_ns,
            "mean_ns": parsing_total_ns / completed,
            "mean_us": parsing_total_ns / completed / 1000.0,
            "definition": "direct sum of fast extraction and full parsing timers",
        }
    }
    for stage in STACKED_COMPONENTS[1:]:
        components[stage] = dict(stages[stage])

    stacked_mean_ns = sum(float(components[name]["mean_ns"]) for name in STACKED_COMPONENTS)
    return {
        "schema_version": 1,
        "instrumentation": "vsr_profile_components",
        "completed_requests": completed,
        "stages": stages,
        "figure_components": components,
        "stacked_direct_mean_us": stacked_mean_ns / 1000.0,
        "request_body_total_mean_us": stages["request_body_total"]["mean_us"],
        "request_body_total_is_inclusive": True,
    }


def capture(url: str, output: Path, timeout: float) -> None:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    parse_snapshot(raw)
    output.write_text(raw, encoding="utf-8")


def render_human(result: dict[str, object]) -> str:
    components = result["figure_components"]
    assert isinstance(components, dict)
    lines = [
        "instrumentation: vsr_profile_components",
        f"completed_requests: {result['completed_requests']}",
    ]
    for name in STACKED_COMPONENTS:
        values = components[name]
        assert isinstance(values, dict)
        lines.append(
            f"{name}: count={values['count']} total_ns={values['total_ns']} "
            f"mean_us={float(values['mean_us']):.6f}"
        )
    lines.extend(
        (
            f"stacked_direct_mean_us: {float(result['stacked_direct_mean_us']):.6f}",
            "request_body_total_mean_us: "
            f"{float(result['request_body_total_mean_us']):.6f} (inclusive, not stacked)",
        )
    )
    return "\n".join(lines)


def render_csv(result: dict[str, object], output: object = sys.stdout) -> None:
    components = result["figure_components"]
    assert isinstance(components, dict)
    writer = csv.writer(output)
    writer.writerow(("component", "count", "total_ns", "mean_ns", "mean_us"))
    for name in STACKED_COMPONENTS:
        values = components[name]
        assert isinstance(values, dict)
        writer.writerow(
            (
                name,
                values["count"],
                values["total_ns"],
                f"{float(values['mean_ns']):.3f}",
                f"{float(values['mean_us']):.6f}",
            )
        )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--url", required=True)
    capture_parser.add_argument("--output", type=Path, required=True)
    capture_parser.add_argument("--timeout", type=float, default=5.0)

    summary_parser = subparsers.add_parser("summarize")
    summary_parser.add_argument("--before", type=Path, required=True)
    summary_parser.add_argument("--after", type=Path, required=True)
    summary_parser.add_argument("--expected-completed", type=int)
    summary_parser.add_argument("--format", choices=("human", "json", "csv"), default="human")
    args = parser.parse_args(argv)

    try:
        if args.action == "capture":
            capture(args.url, args.output, args.timeout)
            return 0
        result = summarize_snapshots(
            args.before.read_text(encoding="utf-8"),
            args.after.read_text(encoding="utf-8"),
            args.expected_completed,
        )
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    if args.format == "json":
        json.dump(result, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    elif args.format == "csv":
        render_csv(result)
    else:
        print(render_human(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
