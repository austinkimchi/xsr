#!/usr/bin/env python3
"""Maintain deterministic benchmark-run manifests without overwriting trials."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--profile")
    parser.add_argument("--mode")
    parser.add_argument("--trials", type=int)
    parser.add_argument("--duration")
    parser.add_argument("--warmup-duration")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--systems")
    parser.add_argument("--include-stress", choices=("0", "1"))
    parser.add_argument("--xsr-warmup-lifecycle")
    parser.add_argument("--configuration")
    parser.add_argument("--trial", type=int)
    parser.add_argument("--order", nargs="+")
    args = parser.parse_args()
    if args.path.exists():
        data = json.loads(args.path.read_text(encoding="utf-8"))
    else:
        data = {"trials": []}
    if args.run_id:
        data.update({
            "run_id": args.run_id, "profile": args.profile, "mode": args.mode, "trial_count": args.trials,
            "duration": args.duration, "warmup_duration": args.warmup_duration, "random_seed": args.seed,
            "systems": args.systems.split(",") if args.systems else [],
            "include_stress": args.include_stress == "1",
            "xsr_warmup_lifecycle": args.xsr_warmup_lifecycle,
        })
    if args.configuration:
        data.setdefault("trials", []).append({"configuration": args.configuration, "trial": args.trial, "system_order": args.order})
    args.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
