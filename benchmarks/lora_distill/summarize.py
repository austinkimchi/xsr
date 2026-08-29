#!/usr/bin/env python3
"""Render compact correctness and three-path performance summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def percent(value):
    return "--" if value is None else f"{100 * value:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--performance", type=Path)
    parser.add_argument("--parity", type=Path)
    args = parser.parse_args()
    report = json.loads(args.evaluation.read_text())
    labels = {
        "teacher": "VSR mmBERT teacher", "supervised_float": "Supervised FNV student",
        "distilled_float": "Distilled FNV student", "distilled_int8": "Quantized distilled student",
    }
    print("| Model | Teacher agreement | Accuracy | Footprint |")
    print("| --- | ---: | ---: | ---: |")
    for key, label in labels.items():
        item = report["models"][key]
        footprint = "~56 KiB" if key == "distilled_int8" else "--"
        print(f"| {label} | {percent(item['teacher_agreement'])} | {percent(item['accuracy'])} | {footprint} |")
    if args.parity:
        parity = json.loads(args.parity.read_text())
        if parity.get("agreement") != 1.0:
            raise SystemExit("refusing to report eBPF quality without 100% parity")
        item = report["models"]["distilled_int8"]
        print(f"| XSR eBPF student | {percent(item['teacher_agreement'])} | {percent(item['accuracy'])} | ~56 KiB |")
    if not args.performance:
        return
    performance = json.loads(args.performance.read_text())
    print("\n| Path | Req/s | Avg latency |")
    print("| --- | ---: | ---: |")
    for key in ("vsr_mmbert", "vsr_distilled", "xsr_distilled"):
        item = performance[key]
        print(f"| {item['label']} | {item['requests_per_second']:.1f} | {item['average_latency_ms']:.3f} ms |")
    teacher = performance["vsr_mmbert"]["requests_per_second"]
    userspace = performance["vsr_distilled"]["requests_per_second"]
    kernel = performance["xsr_distilled"]["requests_per_second"]
    print(f"\nCompression speedup: {userspace / teacher:.2f}x")
    print(f"Kernel-placement speedup: {kernel / userspace:.2f}x")
    print(f"Overall transformed-path speedup: {kernel / teacher:.2f}x")


if __name__ == "__main__":
    main()
