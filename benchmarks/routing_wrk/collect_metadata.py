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
AZURE_INSTANCE_METADATA_URL = (
    "http://169.254.169.254/metadata/instance/compute?api-version=2021-02-01"
)


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


def azure_instance_metadata() -> dict[str, Any]:
    raw = command(
        "curl", "--silent", "--show-error", "--fail", "--noproxy", "*",
        "--connect-timeout", "0.2", "--max-time", "1", "-H", "Metadata:true",
        AZURE_INSTANCE_METADATA_URL,
    )
    if not raw:
        return unavailable()
    try:
        compute = json.loads(raw)
    except json.JSONDecodeError:
        return unavailable()
    return {
        key: compute.get(key)
        for key in ("vmSize", "location", "zone", "platformFaultDomain", "platformUpdateDomain")
        if compute.get(key) is not None
    }


def xsr_warmup_note(lifecycle: str) -> str:
    if lifecycle == "same-process-load-warmup":
        return (
            "XSR reaps closed SOCKMAP connection sets and waits for deterministic "
            "quiescence; warm-up and measurement use the same router process."
        )
    if lifecycle == "disabled":
        return "Load warm-up was disabled; the measured XSR instance was not warmed."
    if lifecycle == "not-selected":
        return "XSR was not selected for this invocation."
    return "See lifecycle field."


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--trials", type=int, required=True)
    parser.add_argument("--duration", required=True)
    parser.add_argument("--warmup-duration", required=True)
    parser.add_argument("--systems", required=True)
    parser.add_argument("--include-stress", choices=("0", "1"), required=True)
    parser.add_argument("--xsr-warmup-lifecycle", required=True)
    parser.add_argument("--xsr-measured-instance-warmed", choices=("true", "false", "not-applicable"), required=True)
    parser.add_argument("--concurrency", required=True)
    parser.add_argument("--rates", required=True)
    parser.add_argument("--wrk-bin", required=True)
    parser.add_argument("--wrk2-bin", required=True)
    parser.add_argument("--vllm-container")
    parser.add_argument("--vsr-container")
    parser.add_argument("--llmrouter-python")
    parser.add_argument("--llmrouter-bin")
    parser.add_argument("--llmrouter-config")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--workload-descriptor", type=Path, required=True)
    parser.add_argument("--xsr-distill-model")
    parser.add_argument("--signal-profile", required=True, choices=("ngram", "bm25", "intent", "mixed"))
    parser.add_argument("--requested-signal-profile", required=True, choices=("auto", "ngram", "bm25", "intent", "mixed"))
    parser.add_argument("--parity-debug", required=True, choices=("0", "1"))
    parser.add_argument("--effective-signal-profile", required=True)
    parser.add_argument("--effective-parity-debug", required=True)
    parser.add_argument("--vsr-verification", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-working-tree", required=True, choices=("clean", "dirty", "unavailable"))
    args = parser.parse_args()
    systems = set(args.systems.split(","))
    uses_docker = bool(systems & {"envoy-only", "vsr"})
    uses_llmrouter = "llmrouter" in systems
    llmrouter_config = Path(args.llmrouter_config) if uses_llmrouter and args.llmrouter_config else None
    workload = json.loads(args.workload_descriptor.read_text(encoding="utf-8"))
    prompts_path = Path(workload["prompts"]["path"])
    actual_prompts_sha = sha256(prompts_path)
    if actual_prompts_sha != workload["prompts"]["sha256"]:
        raise SystemExit(
            f"prompt corpus changed after selection: expected {workload['prompts']['sha256']}, "
            f"found {actual_prompts_sha}"
        )
    distill_model = Path(args.xsr_distill_model).expanduser().resolve() if args.xsr_distill_model else None
    os_release = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace") if Path("/etc/os-release").exists() else None
    metadata: dict[str, Any] = {
        "xsr": {
            "repository_url": command("git", "config", "--get", "remote.origin.url"), "branch": command("git", "branch", "--show-current"),
            "commit": args.source_commit or None, "working_tree": args.source_working_tree,
            "build_profile": "prod" if args.profile == "paper" else "dev", "compiler": command("cc", "--version"),
            "compile_flags": "Makefile OPT_CFLAGS / BPF_CFLAGS", "routing_mode": "SK_SKB/SOCKMAP",
            "distill_model": {
                "path": str(distill_model), "sha256": sha256(distill_model)
            } if distill_model else unavailable(),
            "signals": {
                "requested_profile": args.requested_signal_profile,
                "effective_compiled_profile": args.effective_signal_profile,
                "parity_debug_requested": args.parity_debug == "1",
                "parity_debug": ({"0": False, "1": True}.get(args.effective_parity_debug, "not-built")),
                "keyword_policy": ({"path": str(args.policy), "sha256": sha256(args.policy)}
                                   if args.signal_profile in {"ngram", "bm25", "mixed"} else unavailable()),
            },
        },
        "workload": {
            **workload,
            "policy_path": str(args.policy) if args.signal_profile in {"ngram", "bm25", "mixed"} else None,
            "policy_sha256": sha256(args.policy) if args.signal_profile in {"ngram", "bm25", "mixed"} else None,
        },
        "benchmark": {"mode": args.mode, "profile": args.profile, "trial_count": args.trials, "duration": args.duration,
                      "warmup_duration": args.warmup_duration, "concurrency": args.concurrency, "rates": args.rates,
                      "systems": args.systems.split(","), "include_stress": args.include_stress == "1",
                      "xsr_warmup": {
                          "lifecycle": args.xsr_warmup_lifecycle,
                          "measured_instance_warmed": {"true": True, "false": False}.get(args.xsr_measured_instance_warmed, "not-applicable"),
                          "note": xsr_warmup_note(args.xsr_warmup_lifecycle),
                      },
                      "wrk": {"path": args.wrk_bin, "version": command(args.wrk_bin, "--version")},
                      "wrk2": {"path": args.wrk2_bin, "binary_sha256": sha256(Path(args.wrk2_bin)),
                               "pinned_revision": "44a94c17d8e6a0bac8559b53da76848e430cb7a7",
                               "calibration_patch": {"path": str(WRK2_CALIBRATION_PATCH),
                                                     "sha256": sha256(WRK2_CALIBRATION_PATCH)}}},
        "environment": {"macos_host": unavailable(), "virtualization": command("systemd-detect-virt"),
                        "linux_distribution": os_release, "kernel": platform.release(), "cpu_count": os.cpu_count(),
                        "lscpu": command("lscpu"),
                        "numa_topology": command("lscpu", "--extended=CPU,NODE,SOCKET,CORE"),
                        "memory": command("sh", "-c", "cat /proc/meminfo"),
                        "memory_summary": command("free", "-h"),
                        "azure_instance": azure_instance_metadata(),
                        "network_namespaces": command("ip", "netns", "list"),
                        "interfaces": command("ip", "-details", "link", "show", "veth0"),
                        "offloads": command("ethtool", "-k", "veth0")},
        "docker": {"version": command("docker", "version", "--format", "{{.Server.Version}}") if uses_docker else unavailable(),
                   "vsr": docker_image(args.vsr_container) if "vsr" in systems else unavailable(),
                   "envoy": docker_image(args.vllm_container) if uses_docker else unavailable(),
                   "envoy_version": command("docker", "exec", args.vllm_container, "envoy", "--version") if uses_docker and args.vllm_container else unavailable(),
                   "vsr_version": command("docker", "exec", args.vsr_container, "vllm-sr", "--version") if "vsr" in systems and args.vsr_container else unavailable(),
                   "installation_note": "Installation method: official vLLM Semantic Router production documentation; the deployment was the latest production build at installation time."},
        "llmrouter": {
            "version": command(
                args.llmrouter_python, "-c",
                "from importlib.metadata import version; print(version('llmrouter-lib'))",
            ) if uses_llmrouter and args.llmrouter_python else unavailable(),
            "cli_reported_version": command(args.llmrouter_bin, "version") if uses_llmrouter and args.llmrouter_bin else unavailable(),
            "binary": args.llmrouter_bin if uses_llmrouter and args.llmrouter_bin else unavailable(),
            "config_path": str(llmrouter_config) if llmrouter_config else unavailable(),
            "config_sha256": sha256(llmrouter_config) if llmrouter_config else unavailable(),
            "installed_revision": command(
                args.llmrouter_python, "-c",
                "import json; from importlib.metadata import distribution; "
                "print(json.loads(distribution('llmrouter-lib').read_text('direct_url.json'))['vcs_info']['commit_id'])",
            ) if uses_llmrouter and args.llmrouter_python else unavailable(),
            "pinned_revision": "da3430baaea672743c3957457b0c76faba19876e",
        },
    }
    if args.vsr_verification:
        metadata["vsr_configuration_verification"] = json.loads(
            args.vsr_verification.read_text(encoding="utf-8")
        )
    configs = args.output.parent / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    if args.signal_profile in {"ngram", "bm25", "mixed"}:
        if not args.policy.is_file():
            raise SystemExit(f"keyword policy does not exist: {args.policy}")
        shutil.copy2(args.policy, configs / args.policy.name)
    if llmrouter_config:
        snapshot = configs / f"llmrouter-{llmrouter_config.name}"
        shutil.copy2(llmrouter_config, snapshot)
        metadata["llmrouter"]["config_snapshot"] = {
            "path": str(snapshot),
            "sha256": sha256(snapshot),
        }
    args.output.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
