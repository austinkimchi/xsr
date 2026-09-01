from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import verify_vsr_config


class VSRConfigurationVerificationTest(unittest.TestCase):
    def inspect(self) -> dict[str, object]:
        return {
            "Image": "sha256:image",
            "Config": {"Entrypoint": ["router"], "Cmd": [], "Env": [], "Labels": {}},
            "Mounts": [],
        }

    def test_automatic_bm25_configuration_records_identity_without_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "router.yaml"
            config.write_text("classifier: bm25\n", encoding="utf-8")
            output = root / "run" / "vsr-verification.json"
            inspected = self.inspect()
            inspected["Mounts"] = [{"Source": str(config), "Destination": "/config/router.yaml", "Type": "bind"}]
            argv = ["verify_vsr_config.py", "--container", "router", "--profile", "bm25",
                    "--config", str(config), "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ):
                verify_vsr_config.main()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["verification_mode"], "automatic-inspection")
            artifact = result["configuration_artifacts"][0]
            self.assertEqual(artifact["source_path"], str(config))
            self.assertEqual(artifact["sha256"], hashlib.sha256(config.read_bytes()).hexdigest())
            self.assertNotIn("snapshot_path", artifact)
            self.assertFalse((output.parent / "configs").exists())

    def test_unbound_supplied_config_is_not_automatic_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "router.yaml"
            config.write_text("classifier: bm25\n", encoding="utf-8")
            output = root / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--profile", "bm25",
                    "--config", str(config), "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=self.inspect()
            ), self.assertRaisesRegex(SystemExit, "reviewed configuration contract"):
                verify_vsr_config.main()

    def test_opaque_config_requires_exact_reviewed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "router.yaml"
            config.write_text("classifier: proprietary\n", encoding="utf-8")
            digest = hashlib.sha256(config.read_bytes()).hexdigest()
            output = root / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--profile", "ngram",
                    "--config", str(config), "--expected-sha256", digest,
                    "--asserted-profile", "ngram", "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=self.inspect()
            ):
                verify_vsr_config.main()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["verification_mode"], "caller-reviewed-hash-contract")
            self.assertFalse(result["automatic_detection"])

    def test_intent_auto_detection_requires_mmbert_32k_and_lora(self) -> None:
        inspected = self.inspect()
        inspected["Config"] = {
            "Entrypoint": ["router"], "Cmd": ["--model", "mmBERT-32K", "--adapter", "intent-LoRA"],
            "Env": [], "Labels": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--profile", "intent",
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ):
                verify_vsr_config.main()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(result["automatic_detection"])
            self.assertTrue(result["intent_identity_requirements"]["mmbert_32k_marker"])


if __name__ == "__main__":
    unittest.main()
