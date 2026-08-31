#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import prepare_workload as workload


BODY = {"model": "MoM", "messages": [{"role": "user", "content": "intent prompt"}]}


def write_prompts(path: Path, *, annotated: bool = False) -> bytes:
    body = dict(BODY)
    if annotated:
        body["x_expected_route"] = "coding"
    data = (json.dumps(body, separators=(",", ":")) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


class PrepareWorkloadTest(unittest.TestCase):
    def test_explicit_prompt_file_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prompts = Path(directory) / "intent.jsonl"
            original = write_prompts(prompts)
            generator = mock.Mock()
            descriptor = workload.prepare_workload(
                prompts=prompts, explicit=True, workload_id="intent:test", generate_default=generator
            )
            self.assertEqual(prompts.read_bytes(), original)
            generator.assert_not_called()
            self.assertEqual(descriptor["selection"], "explicit")

    def test_default_keyword_workload_generates_only_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            default = Path(directory) / "dataset_prompts.jsonl"

            def generate(path: Path) -> None:
                write_prompts(path, annotated=True)

            with mock.patch.object(workload, "DEFAULT_PROMPTS", default):
                descriptor = workload.prepare_workload(
                    prompts=default, explicit=False, workload_id=None, generate_default=generate
                )
            self.assertTrue(descriptor["generated"])
            self.assertEqual(descriptor["identity"]["id"], "speed-bench:qualitative:test")

    def test_unannotated_intent_workload_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prompts = Path(directory) / "intent.jsonl"
            original = write_prompts(prompts)
            generator = mock.Mock(side_effect=AssertionError("must not regenerate explicit prompts"))
            with mock.patch.object(workload, "DEFAULT_PROMPTS", prompts):
                descriptor = workload.prepare_workload(
                    prompts=prompts, explicit=False, workload_id=None, generate_default=generator
                )
            self.assertEqual(prompts.read_bytes(), original)
            generator.assert_not_called()
            self.assertEqual(descriptor["prompts"]["route_distribution"], {"unlabeled": 1})
            self.assertEqual(descriptor["identity"]["kind"], "unknown")

    def test_existing_annotated_default_is_not_assumed_to_be_speed_bench(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prompts = Path(directory) / "dataset_prompts.jsonl"
            write_prompts(prompts, annotated=True)
            with mock.patch.object(workload, "DEFAULT_PROMPTS", prompts):
                descriptor = workload.prepare_workload(
                    prompts=prompts, explicit=False, workload_id=None, generate_default=mock.Mock()
                )
            self.assertEqual(descriptor["identity"]["kind"], "unknown")

    def test_provenance_uses_actual_hash_and_manifest_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prompts = Path(directory) / "intent.jsonl"
            data = write_prompts(prompts)
            digest = hashlib.sha256(data).hexdigest()
            workload.sidecar_path(prompts).write_text(json.dumps({
                "prompts_sha256": digest,
                "workload_identity": {
                    "id": "intent-manifest:heldout:test",
                    "kind": "intent-manifest",
                    "manifest": {"path": "/data/heldout.jsonl", "sha256": "manifest-sha"},
                    "split": "test",
                },
            }), encoding="utf-8")
            descriptor = workload.prepare_workload(
                prompts=prompts, explicit=True, workload_id=None, generate_default=mock.Mock()
            )
            self.assertEqual(descriptor["prompts"]["sha256"], digest)
            self.assertEqual(descriptor["identity"]["id"], "intent-manifest:heldout:test")
            self.assertEqual(descriptor["identity"]["source"], "prompt-sidecar")


if __name__ == "__main__":
    unittest.main()
