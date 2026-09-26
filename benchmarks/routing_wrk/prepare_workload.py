#!/usr/bin/env python3
"""Select an immutable benchmark prompt corpus and capture its provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPTS = ROOT / "benchmarks/dataset_prompts.jsonl"
SIDECAR_SUFFIX = ".metadata.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sidecar_path(path: Path) -> Path:
    return Path(f"{path}{SIDECAR_SUFFIX}")


def prompt_details(path: Path) -> dict[str, Any]:
    routes: dict[str, int] = {}
    count = 0
    with path.open(encoding="utf-8") as prompts:
        for line_number, line in enumerate(prompts, start=1):
            if not line.strip():
                continue
            try:
                body = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON in {path} at line {line_number}: {exc}") from exc
            if not isinstance(body, dict):
                raise ValueError(f"prompt body in {path} at line {line_number} is not an object")
            count += 1
            route = str(body.get("x_expected_route", "unlabeled"))
            routes[route] = routes.get(route, 0) + 1
    if count == 0:
        raise ValueError(f"prompt file is empty: {path}")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "prompt_count": count,
        "route_distribution": routes,
    }


def identity_from_sidecar(path: Path, prompt_hash: str) -> tuple[dict[str, Any] | None, str | None]:
    metadata_path = sidecar_path(path)
    if not metadata_path.is_file():
        return None, None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, None
    if metadata.get("prompts_sha256") != prompt_hash:
        return None, None
    identity = metadata.get("workload_identity")
    if not isinstance(identity, dict) or not identity.get("id"):
        return None, None
    result = dict(identity)
    result["source"] = "prompt-sidecar"
    return result, str(metadata_path.resolve())


def prepare_workload(
    *,
    prompts: Path,
    explicit: bool,
    workload_id: str | None,
    generate_default: Callable[[Path], None],
) -> dict[str, Any]:
    selected = prompts.expanduser().resolve()
    generated = False
    if not selected.is_file():
        if explicit:
            raise FileNotFoundError(f"explicit prompt file does not exist: {selected}")
        if selected != DEFAULT_PROMPTS.resolve():
            raise ValueError("automatic generation is allowed only for the default prompt path")
        generate_default(selected)
        generated = True
    if not selected.is_file():
        raise FileNotFoundError(f"prompt generator did not create {selected}")

    prompts_info = prompt_details(selected)
    sidecar = None
    if workload_id:
        identity: dict[str, Any] = {
            "id": workload_id,
            "kind": "caller-supplied",
            "source": "WORKLOAD_ID",
        }
    else:
        inferred, sidecar = identity_from_sidecar(selected, prompts_info["sha256"])
        if inferred:
            identity = inferred
        elif not explicit and generated:
            identity = {
                "id": "speed-bench:qualitative:test",
                "kind": "keyword-dataset",
                "source": "default-keyword-workload",
                "dataset": {"name": "speed-bench", "config": "qualitative", "split": "test"},
            }
        else:
            identity = {
                "id": None,
                "kind": "unknown",
                "source": "not-determined",
                "note": "Set WORKLOAD_ID or export a prompt sidecar to identify this corpus.",
            }

    return {
        "selection": "explicit" if explicit else "default",
        "generated": generated,
        "prompts": prompts_info,
        "identity": identity,
        "identity_sidecar": sidecar,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--explicit", action="store_true")
    parser.add_argument("--workload-id")
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()

    def generate_default(output: Path) -> None:
        print(f"Generating default keyword workload at {output}...")
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "benchmarks/routing_wrk/export_prompts.py"),
                "--config", str(args.policy),
                "--output", str(output),
            ],
            check=True,
        )

    descriptor = prepare_workload(
        prompts=args.prompts,
        explicit=args.explicit,
        workload_id=args.workload_id,
        generate_default=generate_default,
    )
    if descriptor["identity"]["id"] is None:
        raise SystemExit(
            "workload identity cannot be determined without guessing; set WORKLOAD_ID "
            "or use an exporter-generated metadata sidecar"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(descriptor, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Using {descriptor['selection']} workload {descriptor['prompts']['path']} "
        f"(sha256={descriptor['prompts']['sha256']}, identity={descriptor['identity']['id'] or 'unknown'})"
    )


if __name__ == "__main__":
    main()
