#!/usr/bin/env python3
"""Capture reproducible benchmark provenance, marking unavailable facts honestly."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WRK2_CALIBRATION_PATCH = ROOT / "benchmarks/routing_wrk/wrk2-calibration-clock-reset.patch"


def command(*args: str) -> str | None:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unavailable() -> dict[str, str]:
    return {"status": "unavailable"}


def docker_image(container: str | None) -> dict[str, Any]:
    if not container or not command("docker", "inspect", container):
        return unavailable()
    raw = command("docker", "inspect", container)
    assert raw
    data = json.loads(raw)[0]
    image_id = data.get("Image")
    image = data.get("Config", {}).get("Image")
    image_info: dict[str, Any] = {"container_name": container, "configured_image": image, "image_id": image_id}
    inspect_image = command("docker", "image", "inspect", image_id) if image_id else None
    if inspect_image:
        details = json.loads(inspect_image)[0]
        image_info.update({
            "repo_digests": details.get("RepoDigests") or [], "created": details.get("Created"),
            "labels": details.get("Config", {}).get("Labels") or {},
        })
    else:
        image_info["repo_digests"] = unavailable()
    return image_info


def prompt_details(path: Path) -> dict[str, Any]:
    routes: dict[str, int] = {}
    count = 0
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            count += 1
            route = json.loads(line).get("x_expected_route", "unlabeled")
            routes[str(route)] = routes.get(str(route), 0) + 1
    return {"path": str(path), "sha256": sha256(path), "prompt_count": count, "route_distribution": routes,
            "dataset": {"name": "speed-bench", "config": "qualitative", "split": "test"}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--trials", type=int, required=True)
    parser.add_argument("--duration", required=True)
    parser.add_argument("--warmup-duration", required=True)
    parser.add_argument("--concurrency", required=True)
    parser.add_argument("--rates", required=True)
    parser.add_argument("--wrk-bin", required=True)
    parser.add_argument("--wrk2-bin", required=True)
    parser.add_argument("--vllm-container")
    parser.add_argument("--vsr-container")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--prompts", type=Path, required=True)
    args = parser.parse_args()
    status = command("git", "status", "--porcelain") or ""
    os_release = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace") if Path("/etc/os-release").exists() else None
    metadata: dict[str, Any] = {
        "xsr": {
            "repository_url": command("git", "config", "--get", "remote.origin.url"), "branch": command("git", "branch", "--show-current"),
            "commit": command("git", "rev-parse", "HEAD"), "working_tree": "clean" if not status else "dirty",
            "build_profile": "prod" if args.profile == "paper" else "dev", "compiler": command("cc", "--version"),
            "compile_flags": "Makefile OPT_CFLAGS / BPF_CFLAGS", "routing_mode": "SK_SKB/SOCKMAP",
        },
        "workload": {"policy_path": str(args.policy), "policy_sha256": sha256(args.policy), "prompts": prompt_details(args.prompts)},
        "benchmark": {"mode": args.mode, "profile": args.profile, "trial_count": args.trials, "duration": args.duration,
                      "warmup_duration": args.warmup_duration, "concurrency": args.concurrency, "rates": args.rates,
                      "wrk": {"path": args.wrk_bin, "version": command(args.wrk_bin, "--version")},
                      "wrk2": {"path": args.wrk2_bin, "binary_sha256": sha256(Path(args.wrk2_bin)),
                               "pinned_revision": "44a94c17d8e6a0bac8559b53da76848e430cb7a7",
                               "calibration_patch": {"path": str(WRK2_CALIBRATION_PATCH),
                                                     "sha256": sha256(WRK2_CALIBRATION_PATCH)}}},
        "environment": {"macos_host": unavailable(), "virtualization": unavailable(), "linux_distribution": os_release,
                        "kernel": platform.release(), "cpu_count": os.cpu_count(),
                        "memory": command("sh", "-c", "grep MemTotal /proc/meminfo"),
                        "network_namespaces": command("ip", "netns", "list"),
                        "interfaces": command("ip", "-details", "link", "show", "veth0"),
                        "offloads": command("ethtool", "-k", "veth0")},
        "docker": {"version": command("docker", "version", "--format", "{{.Server.Version}}"), "vsr": docker_image(args.vsr_container),
                   "envoy": docker_image(args.vllm_container),
                   "envoy_version": command("docker", "exec", args.vllm_container, "envoy", "--version") if args.vllm_container else None,
                   "vsr_version": command("docker", "exec", args.vsr_container, "vllm-sr", "--version") if args.vsr_container else unavailable(),
                   "installation_note": "Installation method: official vLLM Semantic Router production documentation; the deployment was the latest production build at installation time."},
    }
    configs = args.output.parent / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.policy, configs / args.policy.name)
    if args.vllm_container:
        effective = command("docker", "exec", args.vllm_container, "sh", "-c", "cat /etc/envoy/envoy.yaml")
        if effective:
            envoy_config = configs / "vsr-envoy.yaml"
            envoy_config.write_text(effective + "\n", encoding="utf-8")
            metadata["docker"]["effective_envoy_config"] = {"path": str(envoy_config), "sha256": sha256(envoy_config)}
        else:
            metadata["docker"]["effective_envoy_config"] = unavailable()
    args.output.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
