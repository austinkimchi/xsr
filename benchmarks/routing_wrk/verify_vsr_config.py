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


PROFILE_PATTERNS = {
    "ngram": re.compile(r"(?:n[-_ ]?gram|ngrammatic|jaccard)", re.I),
    "bm25": re.compile(r"\bbm25\b", re.I),
    "intent": re.compile(r"(?:intent|mmbert[-_ ]?32k)", re.I),
}
SELECTOR_PATTERNS = {
    "ngram": re.compile(r"(?:n[-_ ]?gram|ngrammatic|jaccard)", re.I),
    "bm25": re.compile(r"bm25", re.I),
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


def json_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def field_kind(name: str) -> str | None:
    if PROFILE_FIELD.fullmatch(name):
        return "profile"
    if MODEL_FIELD.fullmatch(name):
        return "model"
    if ADAPTER_FIELD.fullmatch(name):
        return "adapter"
    return None


def selector_profile(value: str) -> str | None:
    matches = [name for name, pattern in SELECTOR_PATTERNS.items() if pattern.fullmatch(value.strip())]
    return matches[0] if len(matches) == 1 else None


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
    return result


def container_networks(inspected: dict[str, Any]) -> dict[str, Any]:
    return (inspected.get("NetworkSettings") or {}).get("Networks") or {}


def active_runtime_strings(inspected: dict[str, Any]) -> list[str]:
    config = inspected.get("Config") or {}
    values = [str(value) for value in (config.get("Entrypoint") or [])]
    values.extend(str(value) for value in (config.get("Cmd") or []))
    return values


def mounted_container_paths(path: Path, mounts: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for mount in mounts:
        source = Path(str(mount.get("Source", ""))).expanduser().resolve()
        destination = Path(str(mount.get("Destination", "")))
        if path == source:
            result.append(str(destination))
        elif source.is_dir() and path.is_relative_to(source):
            result.append(str(destination / path.relative_to(source)))
    return result


def runtime_references_path(inspected: dict[str, Any], path: str) -> bool:
    pattern = re.compile(rf"(?<![\w./-]){re.escape(path)}(?![\w./-])")
    return any(pattern.search(value) for value in active_runtime_strings(inspected))


def envoy_configuration_text(container_name: str, inspected: dict[str, Any]) -> str:
    config = inspected.get("Config") or {}
    argv = [str(value) for value in (config.get("Entrypoint") or [])]
    argv.extend(str(value) for value in (config.get("Cmd") or []))
    values: list[str] = []
    config_paths: set[str] = set()
    for index, value in enumerate(argv):
        if value in {"-c", "--config-path"} and index + 1 < len(argv):
            config_paths.add(argv[index + 1])
        elif value.startswith("--config-path="):
            config_paths.add(value.partition("=")[2])
        elif value == "--config-yaml" and index + 1 < len(argv):
            values.append(argv[index + 1])
        elif value.startswith("--config-yaml="):
            values.append(value.partition("=")[2])
    loaded_config_paths: set[str] = set()
    for mount in inspected.get("Mounts") or []:
        source = Path(str(mount.get("Source", "")))
        candidates: list[Path] = []
        destination = str(mount.get("Destination", ""))
        if source.is_dir() and destination:
            for config_path in config_paths:
                try:
                    relative = Path(config_path).relative_to(destination)
                except ValueError:
                    continue
                candidates.append(source / relative)
                if (source / relative).is_file():
                    loaded_config_paths.add(config_path)
        if source.is_file() and destination in config_paths:
            candidates.append(source)
            loaded_config_paths.add(destination)
        for candidate in candidates:
            if (candidate.is_file() and candidate.suffix.lower() in CONFIG_SUFFIXES
                    and candidate.stat().st_size <= 10 * 1024 * 1024):
                values.append(candidate.read_text(encoding="utf-8", errors="replace"))
    for config_path in sorted(config_paths - loaded_config_paths):
        try:
            values.append(subprocess.check_output(
                ["docker", "exec", container_name, "cat", config_path],
                text=True, stderr=subprocess.DEVNULL,
            ))
        except (OSError, subprocess.CalledProcessError):
            continue
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


def yaml_list_items(
    records: list[tuple[int, bool, str, str]],
) -> list[tuple[int, list[tuple[int, bool, str, str]]]]:
    return [
        (record[0], [record, *record_subtree(records, index)])
        for index, record in enumerate(records) if record[1]
    ]


def direct_item_value(
    base_indent: int, item: list[tuple[int, bool, str, str]], key: str,
) -> str | None:
    continuation_indents = [indent for indent, _, _, _ in item[1:] if indent > base_indent]
    direct_indent = min(continuation_indents, default=base_indent)
    for index, (indent, _, item_key, value) in enumerate(item):
        if item_key == key and (index == 0 or indent == direct_indent):
            return value
    return None


def static_resource_items(
    records: list[tuple[int, bool, str, str]], key: str,
) -> list[list[tuple[int, bool, str, str]]]:
    """Return list items for one direct static_resources sequence."""
    static_index = next(
        (index for index, (indent, is_item, item_key, _) in enumerate(records)
         if indent == 0 and not is_item and item_key == "static_resources"),
        None,
    )
    if static_index is None:
        return []
    static_end = static_index + 1
    while static_end < len(records) and records[static_end][0] > 0:
        static_end += 1
    children = records[static_index + 1:static_end]
    child_indents = [indent for indent, _, _, _ in children]
    if not child_indents:
        return []
    child_indent = min(child_indents)
    key_offset = next(
        (offset for offset, (indent, is_item, item_key, _) in enumerate(children)
         if indent == child_indent and not is_item and item_key == key),
        None,
    )
    if key_offset is None:
        return []
    key_index = static_index + 1 + key_offset
    items: list[list[tuple[int, bool, str, str]]] = []
    index = key_index + 1
    while index < static_end:
        indent, is_item, _, _ = records[index]
        if indent < child_indent or (indent == child_indent and not is_item):
            break
        if indent != child_indent or not is_item:
            index += 1
            continue
        end = index + 1
        while end < static_end and records[end][0] > child_indent:
            end += 1
        items.append(records[index:end])
        index = end
    return items


def direct_child(
    records: list[tuple[int, bool, str, str]], key: str,
) -> list[tuple[int, bool, str, str]]:
    """Return one direct mapping child and its subtree, or an empty list."""
    if not records:
        return []
    base_indent = records[0][0]
    child_indents = [indent for indent, _, _, _ in records[1:] if indent > base_indent]
    if not child_indents:
        return []
    child_indent = min(child_indents)
    for index, (indent, is_item, item_key, _) in enumerate(records[1:], start=1):
        if indent == child_indent and not is_item and item_key == key:
            return [records[index], *record_subtree(records, index)]
    return []


def listener_port(listener: list[tuple[int, bool, str, str]]) -> int | None:
    address = direct_child(listener, "address")
    socket_address = direct_child(address, "socket_address")
    port = direct_child(socket_address, "port_value")
    if not port or not port[0][3].isdigit():
        return None
    return int(port[0][3])


def active_extproc_endpoints(
    listener: list[tuple[int, bool, str, str]],
    clusters: list[list[tuple[int, bool, str, str]]],
) -> list[tuple[str, str]]:
    """Return ExtProc endpoints referenced only by the measured listener."""
    cluster_names: set[str] = set()
    direct_targets: list[str] = []
    items = yaml_list_items(listener)
    for base_indent, item in items:
        if direct_item_value(base_indent, item, "name") == "envoy.filters.http.ext_proc":
            for _, _, child_key, child_value in item:
                if child_key == "cluster_name" and child_value:
                    cluster_names.add(child_value)
                elif child_key in {"target_uri", "uri"} and child_value:
                    direct_targets.append(child_value)

    endpoints = [("direct", target) for target in direct_targets]
    for item in clusters:
        base_indent = item[0][0]
        cluster_name = direct_item_value(base_indent, item, "name")
        if cluster_name in cluster_names:
            for _, _, child_key, child_value in item:
                if child_key in {"address", "socket_address", "target_uri"} and child_value:
                    endpoints.append((cluster_name, child_value))
    return endpoints


def verify_envoy_binding(
    router_name: str, router: dict[str, Any], envoy_name: str, envoy_port: int,
) -> dict[str, Any]:
    same_container = router_name == envoy_name
    envoy = router if same_container else inspect_container(envoy_name)
    router_networks = container_networks(router)
    envoy_networks = container_networks(envoy)
    shared_networks = sorted(set(router_networks) & set(envoy_networks))
    if not same_container and not shared_networks:
        raise SystemExit(
            f"VSR router {router_name!r} and measured Envoy {envoy_name!r} share no Docker network"
        )
    identities = {router_name, str((router.get("Config") or {}).get("Hostname") or "")}
    if same_container:
        identities.update({"localhost", "127.0.0.1", "::1"})
    identity_networks = router_networks if same_container else {
        name: router_networks[name] for name in shared_networks
    }
    for network in identity_networks.values():
        identities.add(str(network.get("IPAddress") or ""))
        identities.update(str(alias) for alias in (network.get("Aliases") or []))
    envoy_text = envoy_configuration_text(envoy_name, envoy)
    records = envoy_yaml_records(envoy_text)
    measured_listeners = [
        listener for listener in static_resource_items(records, "listeners")
        if listener_port(listener) == envoy_port
    ]
    if len(measured_listeners) != 1:
        raise SystemExit(
            f"could not uniquely prove static Envoy listener on measured port {envoy_port} "
            f"(found {len(measured_listeners)})"
        )
    active_endpoints = active_extproc_endpoints(
        measured_listeners[0], static_resource_items(records, "clusters")
    )
    matched_endpoints: list[tuple[str, str, str]] = []
    for target, endpoint in active_endpoints:
        matched = next(
            (identity for identity in sorted(identities, key=len, reverse=True)
             if identity and re.search(rf"(?<![\w.-]){re.escape(identity)}(?![\w.-])", endpoint)),
            None,
        )
        if not matched:
            raise SystemExit(
                f"active ExtProc endpoint {endpoint!r} does not reference VSR router {router_name!r}"
            )
        matched_endpoints.append((target, endpoint, matched))
    if not matched_endpoints:
        raise SystemExit(
            f"could not prove measured Envoy {envoy_name!r} references VSR router {router_name!r}"
        )
    return {
        "mode": "same-container-active-extproc" if same_container else "envoy-config-reference",
        "envoy_container": envoy_name,
        "envoy_image_id": envoy.get("Image"),
        "measured_listener_port": envoy_port,
        "shared_networks": shared_networks,
        "active_extproc_endpoints": [
            {"target": target, "endpoint": endpoint, "matched_router_identity": matched}
            for target, endpoint, matched in matched_endpoints
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--envoy-container", required=True)
    parser.add_argument("--envoy-port", type=int, required=True)
    parser.add_argument("--profile", required=True, choices=("ngram", "bm25", "intent"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--asserted-profile", choices=("ngram", "bm25", "intent"))
    args = parser.parse_args()

    inspected = inspect_container(args.container)
    try:
        deployment_binding = verify_envoy_binding(
            args.container, inspected, args.envoy_container, args.envoy_port
        )
        binding_proven = True
    except SystemExit:
        deployment_binding = {"mode": "automatic-unavailable",
                              "envoy_container": args.envoy_container}
        binding_proven = False
    mounts = inspected.get("Mounts", [])
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
        supplied_config_bound = any(
            runtime_references_path(inspected, container_path)
            for container_path in mounted_container_paths(path, mounts)
        )
    else:
        for mount in mounts:
            source = Path(str(mount.get("Source", "")))
            if (source.is_file() and source.suffix.lower() in CONFIG_SUFFIXES
                    and not SENSITIVE_NAME.search(source.name) and source.stat().st_size <= 10 * 1024 * 1024
                    and runtime_references_path(inspected, str(mount.get("Destination", "")))):
                candidates.append((str(source), source.read_text(encoding="utf-8", errors="replace"), sha256(source)))

    config = inspected.get("Config", {})
    runtime_identity = {
        "argv_sha256": json_sha256({
            "entrypoint": config.get("Entrypoint") or [],
            "cmd": config.get("Cmd") or [],
        }),
        "environment_variable_names": sorted(
            str(value).partition("=")[0] for value in (config.get("Env") or [])
        ),
        "label_names": sorted(str(key) for key in (config.get("Labels") or {})),
        "mounts": [
            {"destination": mount.get("Destination"), "type": mount.get("Type")}
            for mount in inspected.get("Mounts", [])
        ],
    }
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
        selector_profile(value) == args.profile for value in classifier_selectors
    )
    selector_proof = selectors_match and (bool(classifier_selectors) or args.profile == "intent")
    automatic = (detected == [args.profile] and supplied_config_bound
                 and selector_proof and binding_proven)
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
        "runtime_identity": runtime_identity,
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
