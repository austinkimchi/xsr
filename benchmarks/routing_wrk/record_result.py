#!/usr/bin/env python3
"""Convert a raw wrk/wrk2 report into a machine-readable trial artifact."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from validate_output import invalid_reasons


def latency_us(value: str) -> float:
    match = re.fullmatch(r"([0-9.]+)(us|ms|s)", value)
    if not match:
        raise ValueError(f"unsupported latency value: {value}")
    amount, unit = match.groups()
    return float(amount) * {"us": 1, "ms": 1_000, "s": 1_000_000}[unit]


def metric(output: str, pattern: str, name: str) -> float:
    match = re.search(pattern, output, re.MULTILINE)
    if not match:
        raise ValueError(f"missing {name}")
    return float(match.group(1))


def parse_metrics(output: str) -> dict[str, float]:
    average = re.search(r"^\s*Latency\s+(\S+)", output, re.MULTILINE)
    percentiles = re.search(r"^\[Lua\] latency percentiles: p50=(\S+) p95=(\S+) p99=(\S+)", output, re.MULTILINE)
    if not average or not percentiles:
        raise ValueError("missing latency metrics")
    return {
        "throughput_rps": metric(output, r"^Requests/sec:\s*([0-9.]+)", "requests/sec"),
        "average_latency_us": latency_us(average.group(1)),
        "p50_latency_us": latency_us(percentiles.group(1)),
        "p95_latency_us": latency_us(percentiles.group(2)),
        "p99_latency_us": latency_us(percentiles.group(3)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument("--topology", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--trial", type=int, required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--exit-status", type=int, required=True)
    args = parser.parse_args()
    raw = args.raw.read_text(encoding="utf-8", errors="replace")
    reasons = invalid_reasons(raw)
    if args.exit_status:
        reasons.insert(0, f"tool exit status={args.exit_status}")
    data: dict[str, object] = {
        "system": args.system,
        "topology": args.topology,
        "mode": args.mode,
        "configuration": args.configuration,
        "trial": args.trial,
        "tool": args.tool,
        "raw_output": str(args.raw),
        "valid": not reasons,
        "failure_reasons": reasons,
    }
    if not reasons:
        try:
            data["metrics"] = parse_metrics(raw)
        except ValueError as error:
            data["valid"] = False
            data["failure_reasons"] = [str(error)]
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
