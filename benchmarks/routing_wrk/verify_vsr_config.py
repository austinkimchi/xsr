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
ACTIVE_CONTAINER_FIELD = re.compile(r"^(?:router|routing|classifier_config|signal|signals|settings|config)$", re.I)


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
            if re.search(r"\s", value.strip()):
                result.append("<redacted-shell-command>")
                continue
            result.append(f"{name}=<redacted>" if separator else name)
            redact_next = not separator
            continue
        if separator:
            result.append(f"{name}={redact_url(setting)}")
        else:
            result.append(redact_url(value))
    return result


def field_kind(name: str) -> str | None:
    if PROFILE_FIELD.fullmatch(name):
        return "profile"
    if MODEL_FIELD.fullmatch(name):
        return "model"
    if ADAPTER_FIELD.fullmatch(name):
        return "adapter"
    return None


def active_values(value: Any, *, within_active_container: bool = True) -> list[tuple[str, str]]:
    """Return values of fields that actively select classifier/model identity."""
    result: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, setting in value.items():
            kind = field_kind(str(key))
            if kind:
                if isinstance(setting, (str, int, float, bool)):
                    result.append((kind, str(setting)))
                elif isinstance(setting, list):
                    result.extend(
                        (kind, str(item)) for item in setting
                        if isinstance(item, (str, int, float, bool))
                    )
            elif (within_active_container and ACTIVE_CONTAINER_FIELD.fullmatch(str(key))
                  and isinstance(setting, (dict, list))):
                result.extend(active_values(setting))
    elif isinstance(value, list) and within_active_container:
        for item in value:
            result.extend(active_values(item))
    return result


def yaml_evidence(text: str) -> list[tuple[str, str]]:
    """Parse conservative YAML key/scalar paths without external dependencies."""
    result: list[tuple[str, str]] = []
    parents: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+#.*$", "", raw_line).rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^(\s*)(?:-\s*)?([A-Za-z_][\w.-]*)\s*:\s*(.*?)\s*$", line)
        if not match or "\t" in match.group(1):
            continue
        indent = len(match.group(1))
        while parents and parents[-1][0] >= indent:
            parents.pop()
        key, setting = match.group(2), match.group(3)
        active_path = all(ACTIVE_CONTAINER_FIELD.fullmatch(parent) for _, parent in parents)
        kind = field_kind(key)
        if setting and active_path and kind:
            result.append((kind, setting.strip().strip("\"'")))
        if not setting:
            parents.append((indent, key))
    return result


def parsed_config_evidence(source: str, text: str) -> list[tuple[str, str]]:
    suffix = Path(source).suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            return yaml_evidence(text)
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
    except (ValueError, TypeError, tomllib.TOMLDecodeError):
        return []
    return active_values(parsed)


def runtime_evidence(config: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    argv = [str(value) for value in (config.get("Entrypoint") or [])]
    argv.extend(str(value) for value in (config.get("Cmd") or []))
    for index, value in enumerate(argv):
        name, separator, setting = value.partition("=")
        field = name.lstrip("-")
        kind = field_kind(field)
        if kind:
            if separator:
                result.append((kind, setting))
            elif index + 1 < len(argv):
                result.append((kind, argv[index + 1]))
    for value in config.get("Env") or []:
        name, separator, setting = str(value).partition("=")
        kind = field_kind(name)
        if separator and kind:
            result.append((kind, setting))
    result.extend(active_values(config.get("Labels") or {}))
    return result


def container_networks(inspected: dict[str, Any]) -> dict[str, Any]:
    return (inspected.get("NetworkSettings") or {}).get("Networks") or {}


def envoy_configuration_text(inspected: dict[str, Any]) -> str:
    config = inspected.get("Config") or {}
    argv = [str(value) for value in (config.get("Entrypoint") or [])]
    argv.extend(str(value) for value in (config.get("Cmd") or []))
    values = list(argv)
    values.extend(f"{key}={value}" for key, value in (config.get("Labels") or {}).items())
    config_paths: set[str] = {"/etc/envoy/envoy.yaml"}
    for index, value in enumerate(argv):
        if value in {"-c", "--config-path"} and index + 1 < len(argv):
            config_paths.add(argv[index + 1])
        elif value.startswith("--config-path="):
            config_paths.add(value.partition("=")[2])
    for mount in inspected.get("Mounts") or []:
        source = Path(str(mount.get("Source", "")))
        candidates = [source]
        destination = str(mount.get("Destination", ""))
        if source.is_dir() and destination:
            for config_path in config_paths:
                try:
                    relative = Path(config_path).relative_to(destination)
                except ValueError:
                    continue
                candidates.append(source / relative)
        for candidate in candidates:
            if (candidate.is_file() and candidate.suffix.lower() in CONFIG_SUFFIXES
                    and candidate.stat().st_size <= 10 * 1024 * 1024):
                values.append(candidate.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(values)


def envoy_yaml_records(text: str) -> list[tuple[int, bool, str, str]]:
    records: list[tuple[int, bool, str, str]] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+#.*$", "", raw_line).rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^(\s*)(-\s*)?([@A-Za-z_][\w.@-]*)\s*:\s*(.*?)\s*$", line)
        if match and "\t" not in match.group(1):
            records.append((len(match.group(1)), bool(match.group(2)), match.group(3),
                            match.group(4).strip().strip("\"'")))
    return records


def record_subtree(
    records: list[tuple[int, bool, str, str]], start: int,
) -> list[tuple[int, bool, str, str]]:
    base_indent = records[start][0]
    end = start + 1
    while end < len(records) and records[end][0] > base_indent:
        end += 1
    return records[start + 1:end]


def active_extproc_endpoints(text: str) -> list[tuple[str, str]]:
    """Return (active target, endpoint) pairs from Envoy's ExtProc configuration."""
    records = envoy_yaml_records(text)
    cluster_names: set[str] = set()
    direct_targets: list[str] = []
    for index, (_, _, key, value) in enumerate(records):
        if key == "name" and value == "envoy.filters.http.ext_proc":
            for _, _, child_key, child_value in record_subtree(records, index):
                if child_key == "cluster_name" and child_value:
                    cluster_names.add(child_value)
                elif child_key in {"target_uri", "uri"} and child_value:
                    direct_targets.append(child_value)

    endpoints = [("direct", target) for target in direct_targets]
    for index, (_, is_list, key, value) in enumerate(records):
        if is_list and key == "name" and value in cluster_names:
            for _, _, child_key, child_value in record_subtree(records, index):
                if child_key in {"address", "socket_address", "target_uri"} and child_value:
                    endpoints.append((value, child_value))
    return endpoints


def verify_envoy_binding(
    router_name: str, router: dict[str, Any], envoy_name: str,
) -> dict[str, Any]:
    if router_name == envoy_name:
        return {"mode": "same-container", "envoy_container": envoy_name,
                "envoy_image_id": router.get("Image")}
    envoy = inspect_container(envoy_name)
    router_networks = container_networks(router)
    envoy_networks = container_networks(envoy)
    shared_networks = sorted(set(router_networks) & set(envoy_networks))
    if not shared_networks:
        raise SystemExit(
            f"VSR router {router_name!r} and measured Envoy {envoy_name!r} share no Docker network"
        )
    identities = {router_name, str((router.get("Config") or {}).get("Hostname") or "")}
    for network in router_networks.values():
        identities.add(str(network.get("IPAddress") or ""))
        identities.update(str(alias) for alias in (network.get("Aliases") or []))
    active_endpoints = active_extproc_endpoints(envoy_configuration_text(envoy))
    matched_pair = next(
        ((target, endpoint, identity) for target, endpoint in active_endpoints
         for identity in sorted(identities, key=len, reverse=True)
         if identity and re.search(rf"(?<![\w.-]){re.escape(identity)}(?![\w.-])", endpoint)),
        None,
    )
    if not matched_pair:
        raise SystemExit(
            f"could not prove measured Envoy {envoy_name!r} references VSR router {router_name!r}"
        )
    target, endpoint, matched = matched_pair
    return {
        "mode": "envoy-config-reference",
        "envoy_container": envoy_name,
        "envoy_image_id": envoy.get("Image"),
        "shared_networks": shared_networks,
        "active_extproc_target": target,
        "active_extproc_endpoint": endpoint,
        "matched_router_identity": matched,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--envoy-container", required=True)
    parser.add_argument("--profile", required=True, choices=("ngram", "bm25", "intent"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--asserted-profile", choices=("ngram", "bm25", "intent"))
    args = parser.parse_args()

    inspected = inspect_container(args.container)
    deployment_binding = verify_envoy_binding(args.container, inspected, args.envoy_container)
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
    searchable = "\n".join(value for _, value in evidence)
    detected = [name for name, pattern in PROFILE_PATTERNS.items() if pattern.search(searchable)]
    classifier_selectors = [value for kind, value in evidence if kind == "profile"]
    model_identity = "\n".join(value for kind, value in evidence if kind == "model")
    adapter_identity = "\n".join(value for kind, value in evidence if kind == "adapter")
    selectors_match = all(
        [name for name, pattern in PROFILE_PATTERNS.items() if pattern.search(value)] == [args.profile]
        for value in classifier_selectors
    )
    selector_proof = selectors_match and (bool(classifier_selectors) or args.profile == "intent")
    automatic = detected == [args.profile] and supplied_config_bound and selector_proof
    if args.profile == "intent" and automatic:
        automatic = bool(
            re.search(r"mmbert[-_ ]?32k", model_identity, re.I)
            and re.search(r"lora|adapter", adapter_identity, re.I)
        )

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
        "active_classifier_selectors": classifier_selectors,
        "container": args.container,
        "container_image_id": inspected.get("Image"),
        "measured_deployment_binding": deployment_binding,
        "configuration_artifacts": artifacts,
        "runtime_identity": json.loads(runtime_identity),
        "intent_identity_requirements": {
            "mmbert_32k_marker": bool(re.search(r"mmbert[-_ ]?32k", model_identity, re.I)),
            "lora_adapter_marker": bool(re.search(r"lora|adapter", adapter_identity, re.I)),
        } if args.profile == "intent" else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"VSR signal profile verified: {args.profile} ({verification_mode})")


if __name__ == "__main__":
    main()
