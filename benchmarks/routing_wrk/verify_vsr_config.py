#!/usr/bin/env python3
"""Fail-closed verification of the effective VSR classifier configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml


PROFILE_PATTERNS = {
    "ngram": re.compile(r"(?:n[-_ ]?gram|ngrammatic|jaccard)", re.I),
    "bm25": re.compile(r"\bbm25\b", re.I),
    "intent": re.compile(r"(?:intent|mmbert[-_ ]?32k)", re.I),
}
CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".toml", ".conf"}
SENSITIVE_NAME = re.compile(r"(?:secret|password|passwd|token|private|credential|api[_-]?key|cert)", re.I)
PROFILE_FIELD = re.compile(r"^(?:classifier|classifier_method|method|routing_method|signal_profile|router_profile)$", re.I)
MODEL_FIELD = re.compile(r"^(?:model|model_name|base_model|tokenizer)$", re.I)
ADAPTER_FIELD = re.compile(r"^(?:adapter|adapter_name|lora|lora_adapter)$", re.I)
ACTIVE_CONTAINER_FIELD = re.compile(r"^(?:router|routing|classifier_config|signal|settings|config)$", re.I)


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
        if separator and SENSITIVE_NAME.search(name):
            result.append(f"{name}=<redacted>")
        elif separator:
            result.append(f"{name}={redact_url(setting)}")
        else:
            result.append(value)
    return result


def redacted_mapping(values: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: "<redacted>" if SENSITIVE_NAME.search(key) else redact_url(str(value))
        for key, value in (values or {}).items()
    }


def redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc:
            return value
        hostname = parsed.hostname or ""
        netloc = hostname
        if parsed.port:
            netloc += f":{parsed.port}"
    except ValueError:
        return "<redacted-invalid-url>" if "://" in value else value
    if parsed.username is not None or parsed.password is not None:
        netloc = f"<redacted>@{netloc}"
    query = urlencode([
        (name, "<redacted>" if SENSITIVE_NAME.search(name) else setting)
        for name, setting in parse_qsl(parsed.query, keep_blank_values=True)
    ])
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))


def redacted_argv(values: list[str] | None) -> list[str]:
    result: list[str] = []
    redact_next = False
    for raw in values or []:
        value = str(raw)
        if redact_next:
            result.append("<redacted>")
            redact_next = False
            continue
        name, separator, setting = value.partition("=")
        if SENSITIVE_NAME.search(name.lstrip("-")):
            result.append(f"{name}=<redacted>" if separator else name)
            redact_next = not separator
            continue
        if separator:
            result.append(f"{name}={redact_url(setting)}")
        else:
            result.append(redact_url(value))
    return result


def active_values(value: Any, *, within_active_container: bool = True) -> list[str]:
    """Return values of fields that actively select classifier/model identity."""
    result: list[str] = []
    if isinstance(value, dict):
        for key, setting in value.items():
            if PROFILE_FIELD.fullmatch(str(key)) or MODEL_FIELD.fullmatch(str(key)) or ADAPTER_FIELD.fullmatch(str(key)):
                if isinstance(setting, (str, int, float, bool)):
                    result.append(str(setting))
                elif isinstance(setting, list):
                    result.extend(str(item) for item in setting if isinstance(item, (str, int, float, bool)))
            elif (within_active_container and ACTIVE_CONTAINER_FIELD.fullmatch(str(key))
                  and isinstance(setting, (dict, list))):
                result.extend(active_values(setting))
    elif isinstance(value, list) and within_active_container:
        for item in value:
            result.extend(active_values(item))
    return result


def parsed_config_evidence(source: str, text: str) -> list[str]:
    suffix = Path(source).suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            parsed = yaml.safe_load(text)
        elif suffix == ".json":
            parsed = json.loads(text)
        elif suffix == ".toml":
            parsed = tomllib.loads(text)
        elif suffix == ".conf":
            parsed = {}
            for line in text.splitlines():
                stripped = line.split("#", 1)[0].strip()
                if "=" in stripped:
                    name, setting = stripped.split("=", 1)
                    parsed[name.strip()] = setting.strip().strip("\"'")
        else:
            return []
    except (ValueError, TypeError, yaml.YAMLError, tomllib.TOMLDecodeError):
        return []
    return active_values(parsed)


def runtime_evidence(config: dict[str, Any]) -> list[str]:
    result: list[str] = []
    argv = [str(value) for value in (config.get("Entrypoint") or [])]
    argv.extend(str(value) for value in (config.get("Cmd") or []))
    for index, value in enumerate(argv):
        name, separator, setting = value.partition("=")
        field = name.lstrip("-")
        if PROFILE_FIELD.fullmatch(field) or MODEL_FIELD.fullmatch(field) or ADAPTER_FIELD.fullmatch(field):
            if separator:
                result.append(setting)
            elif index + 1 < len(argv):
                result.append(argv[index + 1])
    for value in config.get("Env") or []:
        name, separator, setting = str(value).partition("=")
        if separator and (PROFILE_FIELD.fullmatch(name) or MODEL_FIELD.fullmatch(name) or ADAPTER_FIELD.fullmatch(name)):
            result.append(setting)
    result.extend(active_values(config.get("Labels") or {}))
    return result


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
        "entrypoint": redacted_argv(config.get("Entrypoint")),
        "cmd": redacted_argv(config.get("Cmd")),
        "environment": redacted_environment(config.get("Env")),
        "labels": redacted_mapping(config.get("Labels")),
        "mounts": [{"source": m.get("Source"), "destination": m.get("Destination"), "type": m.get("Type")}
                   for m in inspected.get("Mounts", [])],
    }, sort_keys=True)
    # Mount/source paths are provenance only: profile-looking path components
    # must never count as automatic classifier evidence.
    evidence = runtime_evidence(config)
    for source, candidate_text, _ in candidates:
        evidence.extend(parsed_config_evidence(source, candidate_text))
    searchable = "\n".join(evidence)
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
