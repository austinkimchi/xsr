#!/usr/bin/env python3
"""Run and aggregate a randomized fixed-rate Python latency campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from .latency import mean, mean_ci95_five_trials
except ImportError:
    from latency import mean, mean_ci95_five_trials


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_PROMPTS = ROOT / "benchmarks/dataset_prompts.jsonl"


def read_systems(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value:
        raise ValueError("systems JSON must be a non-empty object mapping system names to URLs")
    if any(not isinstance(name, str) or not isinstance(url, str) for name, url in value.items()):
        raise ValueError("every system name and URL must be a string")
    return value


def invoke_client(
    args: argparse.Namespace, system: str, url: str, rate: int, trial: int, order: int
) -> None:
    trial_dir = args.output_dir / "raw" / f"rate-{rate}" / f"trial-{trial:02d}" / system
    trial_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.python),
        str(HERE / "client.py"),
        "--url", url,
        "--rate", str(rate),
        "--connections", str(args.connections),
        "--duration", str(args.duration),
        "--warmup", str(args.warmup),
        "--timeout", str(args.timeout),
        "--prompts", str(args.prompts),
        "--system", system,
        "--trial", str(trial),
        "--output-dir", str(trial_dir),
    ]
    if args.connection_audit and rate == args.rates[0] and trial == 1 and order == 0:
        command.append("--connection-audit")
    prefix = ["ip", "netns", "exec", args.netns] if args.netns else []
    if prefix and os.geteuid() != 0:
        prefix.insert(0, "sudo")
    full_command = prefix + command
    with (trial_dir / "command.txt").open("w", encoding="utf-8") as output:
        output.write(shlex.join(full_command) + "\n")
    with (trial_dir / "stdout.txt").open("w", encoding="utf-8") as output:
        subprocess.run(full_command, check=True, stdout=output, stderr=subprocess.STDOUT)


def aggregate(output_dir: Path, expected_trials: int) -> list[dict[str, Any]]:
    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in output_dir.glob("raw/**/summary.json")]
    grouped: dict[tuple[str, float], list[dict[str, Any]]] = {}
    for summary in summaries:
        grouped.setdefault((summary["system"], summary["requested_rps"]), []).append(summary)
    rows: list[dict[str, Any]] = []
    for (system, rate), trials in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
        if len(trials) != expected_trials:
            raise RuntimeError(f"{system} at {rate:g} RPS has {len(trials)} summaries, expected {expected_trials}")
        trial_means = [trial["actual_latency_us"]["mean"] for trial in trials]
        latency_mean, latency_ci = mean_ci95_five_trials(trial_means)
        rows.append(
            {
                "system": system,
                "requested_rps": rate,
                "trials": len(trials),
                "latency_mean_us": latency_mean,
                "latency_ci95_us": latency_ci,
                "mean_p50_us": mean(trial["actual_latency_us"]["p50"] for trial in trials),
                "mean_p95_us": mean(trial["actual_latency_us"]["p95"] for trial in trials),
                "mean_p99_us": mean(trial["actual_latency_us"]["p99"] for trial in trials),
                "achieved_rps": mean(trial["achieved_rps"] for trial in trials),
                "scheduling_delay_mean_us": mean(trial["scheduling_delay_us"]["mean"] for trial in trials),
                "scheduling_delay_p95_us": mean(trial["scheduling_delay_us"]["p95"] for trial in trials),
                "interarrival_mean_us": mean(trial["interarrival_us"]["mean"] for trial in trials),
                "interarrival_median_us": mean(trial["interarrival_us"]["median"] for trial in trials),
                "interarrival_p5_us": mean(trial["interarrival_us"]["p5"] for trial in trials),
                "interarrival_p95_us": mean(trial["interarrival_us"]["p95"] for trial in trials),
                "http_errors": sum(trial["http_errors"] for trial in trials),
                "connection_errors": sum(trial["connection_errors"] for trial in trials),
                "timeout_errors": sum(trial["timeout_errors"] for trial in trials),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError("no completed summaries found")
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_evidence(args: argparse.Namespace, systems: dict[str, str], rows: list[dict[str, Any]]) -> None:
    (args.output_dir / "README.md").write_text(
        "# Python fixed-rate latency benchmark\n\n"
        "Latencies are direct "
        "`response_complete_ns - request_start_ns` measurements and are not "
        "coordinated-omission corrected. See `AUDIT.md` and per-trial provenance.\n",
        encoding="utf-8",
    )
    (args.output_dir / "AUDIT.md").write_text(
        "# Audit\n\n"
        f"- Rates: `{args.rates}` total global RPS\n"
        f"- Connections: `{args.connections}` persistent, single-flight workers\n"
        f"- Warm-up: `{args.warmup}` seconds; duration: `{args.duration}` seconds\n"
        f"- Trials: `{args.trials}`; random seed: `{args.seed}`\n"
        f"- Namespace: `{args.netns or 'current'}`\n"
        f"- Systems: `{json.dumps(systems, sort_keys=True)}`\n"
        "- Each request is assigned `sequence % connections`; one global absolute monotonic clock is used.\n"
        "- Late requests remain queued for their assigned worker and retain their original scheduled timestamp.\n"
        "- aiohttp HTTP/1.1 sessions have connector limits of one; no pipelining is used.\n",
        encoding="utf-8",
    )
    manifest = {
        "rates": args.rates,
        "connections": args.connections,
        "duration_seconds": args.duration,
        "warmup_seconds": args.warmup,
        "trials": args.trials,
        "seed": args.seed,
        "systems": systems,
        "prompts": str(args.prompts.resolve()),
    }
    (args.output_dir / "campaign.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pacing_fields = [
        "system", "requested_rps", "interarrival_mean_us", "interarrival_median_us",
        "interarrival_p5_us", "interarrival_p95_us", "scheduling_delay_mean_us",
        "scheduling_delay_p95_us",
    ]
    write_csv(
        args.output_dir / "pacing-summary.csv",
        [{field: row[field] for field in pacing_fields} for row in rows],
    )
    checksum_lines = []
    for path in sorted(args.output_dir.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            checksum_lines.append(f"{digest}  {path.relative_to(args.output_dir)}")
    (args.output_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--systems", type=Path, required=True, help="JSON object mapping names to URLs")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rates", type=int, nargs="+", default=[100])
    parser.add_argument("--connections", type=int, default=4)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--duration", type=float, default=40)
    parser.add_argument("--warmup", type=float, default=3)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--seed", type=int, default=20260912)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    # Keep a virtual-environment executable path intact; Path.resolve() would
    # dereference it to the system interpreter and lose the aiohttp environment.
    parser.add_argument("--python", type=Path, default=Path(sys.executable).absolute())
    parser.add_argument("--netns", default="ns1", help="empty string runs in the current namespace")
    parser.add_argument("--connection-audit", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    systems = read_systems(args.systems)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    orders: list[dict[str, Any]] = []
    for rate in args.rates:
        for trial in range(1, args.trials + 1):
            order = list(systems)
            random.Random(args.seed + rate + trial + args.connections).shuffle(order)
            orders.append({"rate": rate, "trial": trial, "systems": order})
            for position, system in enumerate(order):
                invoke_client(args, system, systems[system], rate, trial, position)
    (args.output_dir / "system-order.json").write_text(
        json.dumps(orders, indent=2) + "\n", encoding="utf-8"
    )
    rows = aggregate(args.output_dir, args.trials)
    write_csv(args.output_dir / "aggregate-summary.csv", rows)
    write_evidence(args, systems, rows)


if __name__ == "__main__":
    main()
