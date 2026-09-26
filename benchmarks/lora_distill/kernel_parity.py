#!/usr/bin/env python3
"""Sequential Python-int8 to live-eBPF score/prediction parity check."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import struct
import subprocess
import urllib.parse
from pathlib import Path

from core import integer_scores, predict, read_deployment_model, read_jsonl


def bpftool_json(*arguments: str):
    return json.loads(subprocess.check_output(["bpftool", "-j", *arguments], text=True))


def resolve_map_id(explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    # Kernel BPF object names are limited to 15 visible bytes.
    matches = [item for item in bpftool_json("map", "show") if str(item.get("name", "")).startswith("xdp_distill_las")]
    if len(matches) != 1:
        raise SystemExit(
            f"expected one live xdp_distill_last_prediction map, found {len(matches)}; "
            "build and run the explicit parity configuration with 'make parity-build', or pass --map-id"
        )
    return int(matches[0]["id"])


def debug_value(map_id: int) -> tuple[list[int], int, int]:
    item = bpftool_json("map", "lookup", "id", str(map_id), "key", "hex", "00", "00", "00", "00")
    raw = bytes(int(value, 16) if isinstance(value, str) else value for value in item["value"])
    unpacked = struct.unpack("<14iII", raw)
    return list(unpacked[:14]), unpacked[14], unpacked[15]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--url", default="http://10.10.0.1:18081/v1/chat/completions")
    parser.add_argument("--map-id", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    model, map_id = read_deployment_model(args.model), resolve_map_id(args.map_id)
    parsed = urllib.parse.urlsplit(args.url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=30)
    checked = 0
    try:
        for row in read_jsonl(args.prompts):
            prompt = row["prompt"]
            expected_scores = integer_scores(prompt, model.weights, model.bias).astype(int).tolist()
            body = json.dumps({"model": "MoM", "messages": [{"role": "user", "content": prompt}]}, ensure_ascii=False).encode()
            connection.request("POST", parsed.path or "/", body, {
                "Content-Type": "application/json", "Connection": "keep-alive"
            })
            response = connection.getresponse()
            response.read()
            if response.status >= 400:
                raise SystemExit(f"router returned HTTP {response.status} at prompt {checked}")
            scores, intent, bytes_seen = debug_value(map_id)
            if scores != expected_scores or intent != predict(expected_scores):
                raise SystemExit(f"parity failure at prompt {checked}: intent={intent}, expected={predict(expected_scores)}")
            expected_bytes = min(len(prompt.encode("utf-8")), 16_384)
            if bytes_seen != expected_bytes:
                raise SystemExit(f"byte-count parity failure at prompt {checked}: {bytes_seen} != {expected_bytes}")
            checked += 1
    finally:
        connection.close()
    live_maps = []
    for item in bpftool_json("map", "show"):
        name = str(item.get("name", ""))
        if name.startswith("xdp_distill_"):
            live_maps.append({
                key: item[key]
                for key in (
                    "name", "type", "bytes_key", "bytes_value", "max_entries",
                    "bytes_memlock",
                )
                if key in item
            })
    result = {
        "checked": checked,
        "agreement": 1.0,
        "score_parity": True,
        "prediction_parity": True,
        "byte_count_parity": True,
        "all_14_scores_checked_per_prompt": True,
        "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
        "prompt_manifest_sha256": hashlib.sha256(args.prompts.read_bytes()).hexdigest(),
        "live_distill_maps": sorted(live_maps, key=lambda item: item["name"]),
        "live_distill_map_memlock_bytes": sum(
            item.get("bytes_memlock", 0) for item in live_maps
        ),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Python quantized -> eBPF agreement: {checked}/{checked} (100.0%)")


if __name__ == "__main__":
    main()
