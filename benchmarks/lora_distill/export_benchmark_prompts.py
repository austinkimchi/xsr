#!/usr/bin/env python3
"""Export one manifest split in the existing routing_wrk body format."""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from core import read_jsonl, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    rows = [row for row in read_jsonl(args.manifest) if row["student_split"] == args.split]
    if args.limit is not None:
        rows = rows[: args.limit]
    write_jsonl(args.output, (
        {"model": "MoM", "messages": [{"role": "user", "content": row["prompt"]}]}
        for row in rows
    ))
    manifest = args.manifest.expanduser().resolve()
    prompts = args.output.expanduser().resolve()
    identity = {
        "schema_version": 1,
        "prompts_sha256": hashlib.sha256(prompts.read_bytes()).hexdigest(),
        "workload_identity": {
            "id": f"intent-manifest:{manifest.name}:{args.split}",
            "kind": "intent-manifest",
            "manifest": {
                "path": str(manifest),
                "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            },
            "split": args.split,
            "limit": args.limit,
        },
    }
    Path(f"{prompts}.metadata.json").write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(rows)} benchmark request bodies to {args.output}")


if __name__ == "__main__":
    main()
