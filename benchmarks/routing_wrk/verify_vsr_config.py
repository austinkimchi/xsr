#!/usr/bin/env python3
"""Fail-closed verification of the effective VSR classifier configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


PROFILE_PATTERNS = {
    "ngram": re.compile(r"(?:n[-_ ]?gram|ngrammatic|jaccard)", re.I),
    "bm25": re.compile(r"\bbm25\b", re.I),
    "intent": re.compile(r"(?:intent|mmbert[-_ ]?32k)", re.I),
}
CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".toml", ".conf"}
SENSITIVE_NAME = re.compile(r"(?:secret|password|passwd|token|private|credential|api[_-]?key|cert)", re.I)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_container(name: str) -> dict[str, Any]:
    try:
        raw = subprocess.check_output(["docker", "inspect", name], text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"cannot inspect VSR container {name!r}: {error}") from error
    return json.loads(raw)[0]


def redacted_environment(values: list[str] | None) -> list[str]:
    result = []
    for value in values or []:
        name, separator, setting = value.partition("=")
        result.append(f"{name}=<redacted>" if separator and SENSITIVE_NAME.search(name) else value)
    return result


def redacted_mapping(values: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: "<redacted>" if SENSITIVE_NAME.search(key) else value
        for key, value in (values or {}).items()
    }


def non_path_runtime_evidence(config: dict[str, Any]) -> list[str]:
    values: list[str] = []
    values.extend(str(value) for value in (config.get("Entrypoint") or []))
    values.extend(str(value) for value in (config.get("Cmd") or []))
    values.extend(str(value) for value in (config.get("Env") or []))
    values.extend(f"{key}={value}" for key, value in (config.get("Labels") or {}).items())
    return [
        value for value in values
        if "/" not in value and "\\" not in value
        and not any(value.lower().endswith(suffix) for suffix in CONFIG_SUFFIXES)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--profile", required=True, choices=("ngram", "bm25", "intent"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--asserted-profile", choices=("ngram", "bm25", "intent"))
    args = parser.parse_args()

    inspected = inspect_container(args.container)
    mounted_sources = {
        str(Path(str(mount.get("Source", ""))).expanduser().resolve())
        for mount in inspected.get("Mounts", [])
        if mount.get("Source")
    }
    candidates: list[tuple[str, str, str | None]] = []
    supplied_config_bound = True
    if args.config:
        path = args.config.expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"reviewed VSR config is not a file: {path}")
        actual_hash = sha256(path)
        if args.expected_sha256 and actual_hash != args.expected_sha256.lower():
            raise SystemExit(
                f"VSR config hash mismatch: expected {args.expected_sha256.lower()}, found {actual_hash}"
            )
        candidates.append((str(path), path.read_text(encoding="utf-8", errors="replace"), actual_hash))
        supplied_config_bound = str(path) in mounted_sources
    else:
        for mount in inspected.get("Mounts", []):
            source = Path(str(mount.get("Source", "")))
            if (source.is_file() and source.suffix.lower() in CONFIG_SUFFIXES
                    and not SENSITIVE_NAME.search(source.name) and source.stat().st_size <= 10 * 1024 * 1024):
                candidates.append((str(source), source.read_text(encoding="utf-8", errors="replace"), sha256(source)))

    config = inspected.get("Config", {})
    runtime_identity = json.dumps({
        "entrypoint": config.get("Entrypoint"), "cmd": config.get("Cmd"),
        "environment": redacted_environment(config.get("Env")),
        "labels": redacted_mapping(config.get("Labels")),
        "mounts": [{"source": m.get("Source"), "destination": m.get("Destination"), "type": m.get("Type")}
                   for m in inspected.get("Mounts", [])],
    }, sort_keys=True)
    # Mount/source paths are provenance only: profile-looking path components
    # must never count as automatic classifier evidence.
    searchable = "\n".join(non_path_runtime_evidence(config))
    searchable += "\n" + "\n".join(text for _, text, _ in candidates)
    detected = [name for name, pattern in PROFILE_PATTERNS.items() if pattern.search(searchable)]
    automatic = detected == [args.profile] and supplied_config_bound
    if args.profile == "intent" and automatic:
        automatic = bool(re.search(r"mmbert[-_ ]?32k", searchable, re.I) and re.search(r"lora|adapter", searchable, re.I))

    verification_mode = "automatic-inspection"
    if not automatic:
        if not args.config or not args.expected_sha256 or args.asserted_profile != args.profile:
            raise SystemExit(
                f"could not automatically prove VSR profile {args.profile!r} (detected {detected}); "
                "supply VSR_CONFIG_PATH, VSR_CONFIG_SHA256, and matching VSR_SIGNAL_PROFILE "
                "as an explicit reviewed configuration contract"
            )
        verification_mode = "caller-reviewed-hash-contract"

    # Config contents may contain credentials even when their filenames look
    # harmless. Preserve identity without copying sensitive contents into the
    # shareable benchmark result directory.
    artifacts = [
        {"source_path": source, "sha256": digest}
        for source, _, digest in candidates
    ]

    result = {
        "requested_profile": args.profile,
        "verified_profile": args.profile,
        "verification_mode": verification_mode,
        "automatic_detection": automatic,
        "detected_profile_markers": detected,
        "container": args.container,
        "container_image_id": inspected.get("Image"),
        "configuration_artifacts": artifacts,
        "runtime_identity": json.loads(runtime_identity),
        "intent_identity_requirements": {
            "mmbert_32k_marker": bool(re.search(r"mmbert[-_ ]?32k", searchable, re.I)),
            "lora_adapter_marker": bool(re.search(r"lora|adapter", searchable, re.I)),
        } if args.profile == "intent" else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"VSR signal profile verified: {args.profile} ({verification_mode})")


if __name__ == "__main__":
    main()
