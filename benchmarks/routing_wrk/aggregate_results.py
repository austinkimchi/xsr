#!/usr/bin/env python3
"""Aggregate recoverable per-trial benchmark JSON artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


METRICS = ("throughput_rps", "average_latency_us", "p50_latency_us", "p95_latency_us", "p99_latency_us")


def statistics_for(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {key: None for key in ("mean", "stdev", "median", "minimum", "maximum", "ci95")}
    stdev = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "mean": statistics.mean(values), "stdev": stdev, "median": statistics.median(values),
        "minimum": min(values), "maximum": max(values),
        "ci95": 1.96 * stdev / math.sqrt(len(values)) if len(values) > 1 else 0.0,
    }


def aggregate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["mode"], record["configuration"], record["system"], record["topology"])].append(record)
    result: list[dict[str, Any]] = []
    for (mode, configuration, system, topology), group in sorted(grouped.items()):
        valid = [item for item in group if item.get("valid")]
        row: dict[str, Any] = {
            "mode": mode, "configuration": configuration, "system": system, "topology": topology,
            "valid_trial_count": len(valid), "failed_trial_count": len(group) - len(valid),
            "raw_results": [item["raw_output"] for item in group],
            "metrics": {},
        }
        for metric in METRICS:
            values = [float(item["metrics"][metric]) for item in valid]
            row["metrics"][metric] = statistics_for(values)
        result.append(row)
    return result


def write_outputs(run_dir: Path, summary: list[dict[str, Any]]) -> None:
    metadata_path = run_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {"status": "unavailable"}
    (run_dir / "summary.json").write_text(json.dumps({"metadata": metadata, "results": summary}, indent=2) + "\n", encoding="utf-8")
    fields = ["mode", "configuration", "system", "topology", "valid_trial_count", "failed_trial_count"]
    for metric in METRICS:
        fields.extend(f"{metric}_{stat}" for stat in ("mean", "stdev", "median", "minimum", "maximum", "ci95"))
    with (run_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in summary:
            flat = {key: row[key] for key in fields[:6]}
            for metric in METRICS:
                for statistic, value in row["metrics"][metric].items():
                    flat[f"{metric}_{statistic}"] = value
            writer.writerow(flat)
    xsr = metadata.get("xsr", {})
    docker = metadata.get("docker", {})
    workload = metadata.get("workload", {})
    environment = metadata.get("environment", {})
    benchmark = metadata.get("benchmark", {})
    lines = ["# Routing performance summary", "", "## Provenance", "", f"- XSR commit: `{xsr.get('commit', 'unavailable')}` ({xsr.get('working_tree', 'unavailable')})", f"- XSR build/routing: `{xsr.get('build_profile', 'unavailable')}` / `{xsr.get('routing_mode', 'unavailable')}`", f"- Benchmark: `{benchmark.get('profile', 'unavailable')}` / `{benchmark.get('mode', 'unavailable')}`; trials=`{benchmark.get('trial_count', 'unavailable')}`, duration=`{benchmark.get('duration', 'unavailable')}`, warm-up=`{benchmark.get('warmup_duration', 'unavailable')}`", f"- Linux kernel / CPUs: `{environment.get('kernel', 'unavailable')}` / `{environment.get('cpu_count', 'unavailable')}`", f"- Policy SHA-256: `{workload.get('policy_sha256', 'unavailable')}`", f"- Prompt corpus SHA-256: `{workload.get('prompts', {}).get('sha256', 'unavailable') if isinstance(workload.get('prompts'), dict) else 'unavailable'}`", f"- VSR image ID: `{docker.get('vsr', {}).get('image_id', 'unavailable') if isinstance(docker.get('vsr'), dict) else 'unavailable'}`", f"- Envoy image ID/version: `{docker.get('envoy', {}).get('image_id', 'unavailable') if isinstance(docker.get('envoy'), dict) else 'unavailable'}` / `{docker.get('envoy_version', 'unavailable')}`", f"- Raw trial artifacts: [`raw/`](raw/); full provenance: [`metadata.json`](metadata.json)", "", "| Mode | Configuration | System | Topology | Valid | Failed | Throughput mean ± 95% CI |", "| --- | --- | --- | --- | ---: | ---: | ---: |"]
    for row in summary:
        throughput = row["metrics"]["throughput_rps"]
        mean = "unavailable" if throughput["mean"] is None else f"{throughput['mean']:.2f} ± {throughput['ci95']:.2f}"
        lines.append(f"| {row['mode']} | {row['configuration']} | {row['system']} | {row['topology']} | {row['valid_trial_count']} | {row['failed_trial_count']} | {mean} |")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((args.run_dir / "raw").glob("**/result.json"))]
    if not records:
        raise SystemExit(f"no result.json artifacts under {args.run_dir / 'raw'}")
    write_outputs(args.run_dir, aggregate(records))


if __name__ == "__main__":
    main()
