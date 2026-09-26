#!/usr/bin/env python3
"""Read or reset SK_SKB component profiling aggregates."""

from __future__ import annotations

import argparse
import csv
import json
import socket
import sys
from pathlib import Path
from typing import Iterable


STAGES = ("parse_signal", "decision", "redirect")


def request(socket_path: Path, command: str, timeout: float = 2.0) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall(f"profile {command}\n".encode("ascii"))
        client.shutdown(socket.SHUT_WR)
        raw = b"".join(iter(lambda: client.recv(65536), b""))
    return raw.decode("ascii").strip()


def parse_fields(line: str) -> dict[str, int | str]:
    fields: dict[str, int | str] = {}
    for field in line.split():
        key, separator, value = field.partition("=")
        if not separator:
            raise ValueError(f"invalid profiling field: {field!r}")
        try:
            fields[key] = int(value)
        except ValueError:
            fields[key] = value
    return fields


def aggregate_response(raw: str) -> dict[str, object]:
    lines = raw.splitlines()
    if not lines:
        raise ValueError("empty profiling response")
    header = parse_fields(lines[0])
    if header.get("profile_enabled") != 1:
        raise RuntimeError("router was built with SK_PROFILE_COMPONENTS=0")
    if "error" in header:
        raise RuntimeError(f"router profiling read failed: {header['error']}")
    if header.get("stage_count") != len(STAGES):
        raise ValueError("profiling response has an unexpected stage count")
    cpu_count = header.get("cpu_count")
    if not isinstance(cpu_count, int) or cpu_count <= 0:
        raise ValueError("profiling response has an invalid CPU count")
    if len(lines) != cpu_count + 1:
        raise ValueError(
            f"profiling response contains {len(lines) - 1} CPU rows; "
            f"expected {cpu_count}"
        )

    totals = {stage: {"count": 0, "total_ns": 0} for stage in STAGES}
    seen_cpus: set[int] = set()
    for line in lines[1:]:
        row = parse_fields(line)
        cpu = row.get("cpu")
        if not isinstance(cpu, int) or cpu < 0 or cpu >= cpu_count or cpu in seen_cpus:
            raise ValueError(f"invalid or duplicate CPU row: {cpu!r}")
        seen_cpus.add(cpu)
        for stage in STAGES:
            for metric in ("count", "total_ns"):
                value = row.get(f"{stage}_{metric}")
                if not isinstance(value, int) or value < 0:
                    raise ValueError(f"invalid {stage}_{metric} for CPU {cpu}")
                totals[stage][metric] += value

    counts = {totals[stage]["count"] for stage in STAGES}
    if len(counts) != 1:
        raise RuntimeError(
            "stage counts differ; stop request traffic before reading profiling data"
        )
    completed_requests = totals["redirect"]["count"]
    stages: dict[str, dict[str, int | float]] = {}
    for stage in STAGES:
        count = totals[stage]["count"]
        total_ns = totals[stage]["total_ns"]
        mean_ns = total_ns / count if count else 0.0
        stages[stage] = {
            "count": count,
            "total_ns": total_ns,
            "mean_ns": mean_ns,
            "mean_us": mean_ns / 1000.0,
        }
    total_mean_ns = sum(float(stages[stage]["mean_ns"]) for stage in STAGES)
    return {
        "instrumentation": "on",
        "completed_requests": completed_requests,
        "cpu_count": cpu_count,
        "stages": stages,
        "parse_signal_mean_us": stages["parse_signal"]["mean_us"],
        "decision_mean_us": stages["decision"]["mean_us"],
        "redirect_mean_us": stages["redirect"]["mean_us"],
        "total_profiled_kernel_mean_us": total_mean_ns / 1000.0,
    }


def confirm_reset(raw: str) -> None:
    fields = parse_fields(raw)
    if fields.get("profile_enabled") != 1:
        raise RuntimeError("router was built with SK_PROFILE_COMPONENTS=0")
    if fields.get("reset") != "ok":
        raise RuntimeError(f"router profiling reset failed: {fields.get('error', raw)}")


def render_human(result: dict[str, object]) -> str:
    stages = result["stages"]
    assert isinstance(stages, dict)
    lines = [
        "instrumentation: on",
        f"completed_requests: {result['completed_requests']}",
    ]
    for stage in STAGES:
        values = stages[stage]
        assert isinstance(values, dict)
        lines.append(
            f"{stage}: count={values['count']} total_ns={values['total_ns']} "
            f"mean_us={float(values['mean_us']):.6f}"
        )
    lines.append(
        "total_profiled_kernel_mean_us: "
        f"{float(result['total_profiled_kernel_mean_us']):.6f}"
    )
    return "\n".join(lines)


def render_csv(result: dict[str, object], output: object = sys.stdout) -> None:
    stages = result["stages"]
    assert isinstance(stages, dict)
    writer = csv.writer(output)
    writer.writerow(("stage", "count", "total_ns", "mean_ns", "mean_us"))
    for stage in STAGES:
        values = stages[stage]
        assert isinstance(values, dict)
        writer.writerow(
            (
                stage,
                values["count"],
                values["total_ns"],
                f"{float(values['mean_ns']):.3f}",
                f"{float(values['mean_us']):.6f}",
            )
        )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("read", "reset"))
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--format", choices=("human", "json", "csv"), default="human")
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args(argv)

    try:
        raw = request(args.socket, args.action, args.timeout)
        if args.action == "reset":
            confirm_reset(raw)
            print("profiling counters reset")
            return 0
        result = aggregate_response(raw)
    except (ConnectionError, FileNotFoundError, OSError, RuntimeError, ValueError) as error:
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
