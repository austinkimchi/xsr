#!/usr/bin/env python3
"""Verify intent exports stay ordinary request bodies with bound provenance."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "benchmarks/lora_distill/export_benchmark_prompts.py"


class IntentPromptExportTest(unittest.TestCase):
    def test_export_writes_manifest_identity_sidecar_without_route_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            manifest = temp / "heldout.jsonl"
            prompts = temp / "intent.jsonl"
            manifest.write_text(
                json.dumps({"prompt": "classify this intent", "student_split": "test"}) + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, EXPORTER, "--manifest", manifest, "--output", prompts],
                check=True,
                capture_output=True,
                text=True,
            )
            body = json.loads(prompts.read_text(encoding="utf-8"))
            self.assertNotIn("x_expected_route", body)
            sidecar = json.loads(Path(f"{prompts}.metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(sidecar["prompts_sha256"], hashlib.sha256(prompts.read_bytes()).hexdigest())
            self.assertEqual(sidecar["workload_identity"]["kind"], "intent-manifest")
            self.assertEqual(
                sidecar["workload_identity"]["manifest"]["sha256"],
                hashlib.sha256(manifest.read_bytes()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
