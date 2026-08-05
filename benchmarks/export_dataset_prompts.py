#!/usr/bin/env python3
"""Export dataset prompts to JSONL format for wrk/wrk2 Lua benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmark_keyword_routing import parse_args, load_cases, chat_body

def main() -> None:
    parser = argparse.ArgumentParser(description="Export dataset prompts to JSONL")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "dataset_prompts.jsonl")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "policy_literal.yaml")
    parser.add_argument("--per-route", type=int, default=50)
    args = parser.parse_args()

    bench_args = parse_args()
    bench_args.config = args.config
    bench_args.per_route = args.per_route

    cases, _, _ = load_cases(bench_args)

    with args.output.open("w", encoding="utf-8") as f:
        for case in cases:
            body_bytes = chat_body(case.prompt)
            f.write(body_bytes.decode("utf-8") + "\n")

    print(f"Successfully exported {len(cases)} prompts to {args.output}")

if __name__ == "__main__":
    main()
