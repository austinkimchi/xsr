#!/usr/bin/env python3
"""Maintain deterministic benchmark-run manifests without overwriting trials."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None


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
    parser.add_argument("--xsr-measured-instance-warmed", choices=("true", "false", "not-applicable"))
    parser.add_argument("--workload-descriptor", type=Path)
    parser.add_argument("--signal-profile")
    parser.add_argument("--requested-signal-profile")
    parser.add_argument("--parity-debug", choices=("0", "1"))
    parser.add_argument("--effective-signal-profile")
    parser.add_argument("--effective-parity-debug")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--distill-model", type=Path)
    parser.add_argument("--vsr-verification", type=Path)
    parser.add_argument("--configuration")
    parser.add_argument("--trial", type=int)
    parser.add_argument("--order", nargs="+")
    args = parser.parse_args()
    if args.path.exists():
        data = json.loads(args.path.read_text(encoding="utf-8"))
    else:
        data = {"trials": []}
    if args.run_id:
        workload = None
        if args.workload_descriptor:
            workload = json.loads(args.workload_descriptor.read_text(encoding="utf-8"))
        data.update({
            "run_id": args.run_id, "profile": args.profile, "mode": args.mode, "trial_count": args.trials,
            "duration": args.duration, "warmup_duration": args.warmup_duration, "random_seed": args.seed,
            "systems": args.systems.split(",") if args.systems else [],
            "include_stress": args.include_stress == "1",
            "xsr_warmup_lifecycle": args.xsr_warmup_lifecycle,
            "xsr_measured_instance_warmed": {
                "true": True, "false": False
            }.get(args.xsr_measured_instance_warmed, "not-applicable"),
            "workload": workload,
            "signals": {
                "requested_profile": args.requested_signal_profile,
                "effective_compiled_profile": args.effective_signal_profile,
                "parity_debug_requested": args.parity_debug == "1",
                "parity_debug": ({"0": False, "1": True}.get(args.effective_parity_debug, "not-built")),
                "keyword_policy": ({"path": str(args.policy), "sha256": sha256(args.policy)}
                                   if args.signal_profile in {"ngram", "bm25", "mixed"} else None),
                "distill_model": ({"path": str(args.distill_model), "sha256": sha256(args.distill_model)}
                                  if args.distill_model and args.distill_model.is_file() else None),
            },
            "vsr_configuration_verification": (
                json.loads(args.vsr_verification.read_text(encoding="utf-8"))
                if args.vsr_verification else None
            ),
        })
    if args.configuration:
        data.setdefault("trials", []).append({"configuration": args.configuration, "trial": args.trial, "system_order": args.order})
    args.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
