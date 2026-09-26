#!/usr/bin/env python3
"""Run XSR's isolated routing, policy, and forwarding ablations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import statistics
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
NATIVE = ROOT / "build" / "ablation" / "native_benchmark"
DEFAULT_PROMPTS = ROOT / "benchmarks" / "dataset_prompts.jsonl"
T_CRITICAL_95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
                 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}

from benchmarks.policy.generate_keyword_header import load_policy, validate_policy  # noqa: E402
from benchmarks.routing_correctness.benchmark import expected_route  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def user_prompt(record: dict[str, Any]) -> str:
    messages = record.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user" and isinstance(message.get("content"), str):
                return message["content"]
    for field in ("query", "prompt"):
        if isinstance(record.get(field), str):
            return record[field]
    raise ValueError("workload row has no user prompt")


def write_native_workload(source: Path, output: Path) -> int:
    prompts: list[bytes] = []
    with source.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                prompt = user_prompt(json.loads(line)).encode("utf-8")
            except (json.JSONDecodeError, ValueError) as error:
                raise ValueError(f"invalid workload row {line_number}: {error}") from error
            prompts.append(prompt)
    if not prompts:
        raise ValueError("workload is empty")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        handle.write(struct.pack("<I", len(prompts)))
        for prompt in prompts:
            handle.write(struct.pack("<I", len(prompt)))
            handle.write(prompt)
    return len(prompts)


def prompt_texts(source: Path) -> list[str]:
    with source.open(encoding="utf-8") as handle:
        return [user_prompt(json.loads(line)) for line in handle if line.strip()]


def validate_python_reference(signal: str, masks: list[int], prompts: Path) -> dict[str, Any]:
    policy_path = ROOT / "config" / f"policy_{signal}.yaml"
    case_sensitive, routes = validate_policy(load_policy(policy_path))
    priorities = {"coding": 100, "math": 90, "qa": 80, "writing": 70, "others": 0}
    route_bits = {"coding": 0, "others": 1, "math": 2, "qa": 3, "writing": 4}
    mismatches: list[dict[str, Any]] = []
    texts = prompt_texts(prompts)
    if len(texts) != len(masks):
        raise ValueError("native and Python reference prompt counts differ")
    for index, (text, mask) in enumerate(zip(texts, masks)):
        expected, _ = expected_route(text, routes, case_sensitive)
        selected = max((name for name, bit in route_bits.items() if mask & (1 << bit)),
                       key=lambda name: priorities[name], default="others")
        if selected != expected:
            mismatches.append({"index": index, "python_reference": expected, "native_xsr": selected})
    if mismatches:
        raise RuntimeError(f"{signal} differs from the established Python reference: {mismatches[:5]}")
    return {"check": "established-python-reference", "signal": signal,
            "inputs": len(texts), "mismatches": 0}


def run_json(command: list[str], raw_path: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}); see {raw_path}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"command produced no JSON; see {raw_path}")
    return json.loads(lines[-1])


def ci95(values: list[float]) -> tuple[float, float, float]:
    mean = statistics.mean(values)
    if len(values) == 1:
        return mean, 0.0, 0.0
    stdev = statistics.stdev(values)
    df = len(values) - 1
    critical = T_CRITICAL_95.get(df, 1.96 if df >= 30 else 2.0)
    return mean, stdev, critical * stdev / math.sqrt(len(values))


def aggregate(component: str, records: list[dict[str, Any]], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    trial_fields = ["component", "implementation", "trial", "order", "latency_ns_per_operation",
                    "operations_per_second", "operations", "elapsed_ns", "latency_unit", "throughput_unit", "raw_output"]
    with (output / "trials.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=trial_fields)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record[key] for key in trial_fields})
    (output / "trials.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault((str(record["component"]), str(record["implementation"])), []).append(record)
    summary: list[dict[str, Any]] = []
    for (measured_component, implementation), group in sorted(groups.items()):
        latency = [float(row["latency_ns_per_operation"]) for row in group]
        throughput = [float(row["operations_per_second"]) for row in group]
        latency_mean, latency_stdev, latency_ci = ci95(latency)
        throughput_mean, throughput_stdev, throughput_ci = ci95(throughput)
        summary.append({
            "benchmark": component,
            "component": measured_component,
            "implementation": implementation,
            "trials": len(group),
            "primary_metric": "latency_ns_per_operation",
            "latency_unit": "ns/operation",
            "latency_mean": latency_mean,
            "latency_stdev": latency_stdev,
            "latency_ci95_half_width": latency_ci,
            "throughput_unit": "operations/second",
            "operations_per_second_mean": throughput_mean,
            "operations_per_second_stdev": throughput_stdev,
            "operations_per_second_ci95_half_width": throughput_ci,
        })
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (output / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)


def metadata(output: Path, args: argparse.Namespace, prompt_count: int | None) -> None:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=True).stdout)
    data = {
        "schema": "xsr-component-ablation-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "git_working_tree_dirty": dirty,
        "host": {"kernel": platform.release(), "machine": platform.machine(), "cpu_count": os.cpu_count()},
        "protocol": {"trials": args.trials, "duration_seconds": args.duration,
                     "warmup_seconds": args.warmup, "random_seed": args.seed},
        "workload": None if prompt_count is None else {
            "path": str(args.prompts.resolve()), "sha256": sha256(args.prompts), "prompt_count": prompt_count,
        },
        "isolation": {
            "routing_function": "prompt bytes -> one signal implementation -> signal mask; no HTTP, sockets, policy, or forwarding",
            "decision_policy": "precomputed 5-bit signal state -> policy implementation -> route; no signal generation or forwarding",
            "forwarding_path": "HTTP load only; Direct vs fixed-backend SOCKMAP vs router-only Envoy with ExtProc disabled",
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "metadata.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def build_native() -> None:
    subprocess.run(["make", "ablation-native-build"], cwd=ROOT, check=True)


def run_routing(args: argparse.Namespace, suite_dir: Path) -> Path:
    build_native()
    output = suite_dir / "routing-function"
    workload_path = output / "workload.bin"
    count = write_native_workload(args.prompts, workload_path)
    preflight = []
    for signal in ("ngram", "bm25"):
        preflight.append(run_json([str(NATIVE), "verify-routing", signal, str(workload_path)],
                                  output / "raw" / f"preflight-{signal}.txt"))
        native = run_json([str(NATIVE), "dump-routing", signal, "xsr", str(workload_path)],
                          output / "raw" / f"preflight-{signal}-python-reference.txt")
        preflight.append(validate_python_reference(signal, native["signal_masks"], args.prompts))
    (output / "preflight.json").write_text(json.dumps(preflight, indent=2) + "\n", encoding="utf-8")
    records: list[dict[str, Any]] = []
    cases = [(signal, implementation) for signal in ("ngram", "bm25") for implementation in ("reference", "xsr")]
    for trial in range(1, args.trials + 1):
        order = cases.copy()
        random.Random(args.seed + trial).shuffle(order)
        for position, (signal, implementation) in enumerate(order, 1):
            raw = output / "raw" / f"trial-{trial:02d}" / f"{position:02d}-{signal}-{implementation}.txt"
            record = run_json([str(NATIVE), "routing", signal, implementation, str(workload_path),
                               str(args.warmup), str(args.duration)], raw)
            record.update({"trial": trial, "order": position, "latency_unit": "ns/operation",
                           "throughput_unit": "operations/second", "raw_output": str(raw)})
            records.append(record)
    aggregate("routing-function", records, output)
    metadata(output, args, count)
    return output


def run_policy(args: argparse.Namespace, suite_dir: Path) -> Path:
    build_native()
    output = suite_dir / "decision-policy"
    preflight = run_json([str(NATIVE), "verify-policy"], output / "raw" / "preflight.txt")
    (output / "preflight.json").write_text(json.dumps(preflight, indent=2) + "\n", encoding="utf-8")
    records: list[dict[str, Any]] = []
    for trial in range(1, args.trials + 1):
        order = ["reference", "xsr"]
        random.Random(args.seed + trial).shuffle(order)
        for position, implementation in enumerate(order, 1):
            raw = output / "raw" / f"trial-{trial:02d}" / f"{position:02d}-{implementation}.txt"
            record = run_json([str(NATIVE), "policy", implementation, str(args.warmup), str(args.duration)], raw)
            record.update({"trial": trial, "order": position, "latency_unit": "ns/operation",
                           "throughput_unit": "operations/second", "raw_output": str(raw)})
            records.append(record)
    aggregate("decision-policy", records, output)
    metadata(output, args, None)
    return output


def run_forwarding(args: argparse.Namespace, suite_dir: Path) -> Path:
    output = suite_dir / "forwarding-path"
    forwarding_warmup = max(1.0, args.warmup)
    command = [str(ROOT / "benchmarks" / "ablation" / "run_forwarding_path.sh"),
               "--output-dir", str(output), "--trials", str(args.trials),
               "--duration", f"{args.duration:g}s", "--warmup", f"{forwarding_warmup:g}s",
               "--concurrency", str(args.concurrency), "--seed", str(args.seed),
               "--prompts", str(args.prompts)]
    subprocess.run(command, cwd=ROOT, check=True)
    return output


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("component", choices=("routing-function", "decision-policy", "forwarding-path", "all"))
    result.add_argument("--output-dir", type=Path)
    result.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    result.add_argument("--trials", type=int, default=5)
    result.add_argument("--duration", type=float, default=15.0, help="timed seconds per microbenchmark implementation")
    result.add_argument("--warmup", type=float, default=1.0, help="warm-up seconds per implementation")
    result.add_argument("--concurrency", type=int, default=64, help="forwarding-path connections")
    result.add_argument("--seed", type=int, default=20260826)
    result.add_argument("--smoke", action="store_true", help="one short trial (0.1 s microbench, 1 s forwarding)")
    return result


def main() -> None:
    args = parser().parse_args()
    if args.smoke:
        args.trials = 1
        args.duration = 1.0 if args.component in ("forwarding-path", "all") else 0.1
        args.warmup = 0.1
        args.concurrency = min(args.concurrency, 4)
    if args.trials < 1 or args.duration <= 0 or args.warmup < 0 or args.concurrency < 1:
        raise SystemExit("trials, duration, and concurrency must be positive; warmup may be zero")
    if not args.prompts.is_file():
        raise SystemExit(f"prompt corpus does not exist: {args.prompts}")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suite_dir = (args.output_dir or ROOT / "results" / "ablation" / run_id).resolve()
    suite_dir.mkdir(parents=True, exist_ok=True)
    completed: dict[str, str] = {}
    if args.component in ("routing-function", "all"):
        completed["routing-function"] = str(run_routing(args, suite_dir))
    if args.component in ("decision-policy", "all"):
        completed["decision-policy"] = str(run_policy(args, suite_dir))
    if args.component in ("forwarding-path", "all"):
        completed["forwarding-path"] = str(run_forwarding(args, suite_dir))
    (suite_dir / "suite.json").write_text(json.dumps({"schema": "xsr-component-ablation-suite-v1",
                                                       "components": completed}, indent=2) + "\n", encoding="utf-8")
    print(f"Ablation results: {suite_dir}")


if __name__ == "__main__":
    main()
