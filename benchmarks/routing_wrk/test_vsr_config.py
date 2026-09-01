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
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router", "--profile", "bm25",
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
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router", "--profile", "bm25",
                    "--config", str(config), "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=self.inspect()
            ), self.assertRaisesRegex(SystemExit, "reviewed configuration contract"):
                verify_vsr_config.main()

    def test_profile_marker_in_mount_path_is_not_automatic_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "bm25"
            config_dir.mkdir()
            config = config_dir / "router.yaml"
            config.write_text("classifier: proprietary\n", encoding="utf-8")
            output = root / "run" / "vsr-verification.json"
            inspected = self.inspect()
            inspected["Mounts"] = [{"Source": str(config), "Destination": "/configs/bm25/router.yaml", "Type": "bind"}]
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router", "--profile", "bm25",
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ), self.assertRaisesRegex(SystemExit, "reviewed configuration contract"):
                verify_vsr_config.main()

    def test_comment_and_unused_fields_are_not_automatic_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "router.yaml"
            config.write_text(
                "# classifier: bm25\nclassifier: proprietary\n"
                "examples:\n  - classifier: bm25\n",
                encoding="utf-8",
            )
            output = root / "run" / "vsr-verification.json"
            inspected = self.inspect()
            inspected["Mounts"] = [{"Source": str(config), "Destination": "/config/router.yaml", "Type": "bind"}]
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router", "--profile", "bm25",
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ), self.assertRaisesRegex(SystemExit, "reviewed configuration contract"):
                verify_vsr_config.main()

    def test_runtime_identity_redacts_sensitive_argv(self) -> None:
        inspected = self.inspect()
        inspected["Config"] = {
            "Entrypoint": ["router"],
            "Cmd": ["--classifier", "bm25", "--api-key", "top-secret",
                    "--endpoint=https://user:pass@example.test/path?token=secret"],
            "Env": [], "Labels": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router", "--profile", "bm25",
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ):
                verify_vsr_config.main()
            serialized = output.read_text(encoding="utf-8")
            self.assertNotIn("top-secret", serialized)
            self.assertNotIn("user:pass", serialized)
            self.assertNotIn("token=secret", serialized)
            self.assertIn("<redacted>", serialized)

    def test_runtime_identity_redacts_shell_form_command(self) -> None:
        inspected = self.inspect()
        inspected["Config"] = {
            "Entrypoint": ["sh", "-c"],
            "Cmd": ["router --classifier bm25 --token top-secret",
                    "router --endpoint https://alice:password@example.test"],
            "Env": ["CLASSIFIER=bm25"], "Labels": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--profile", "bm25", "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ):
                verify_vsr_config.main()
            serialized = output.read_text(encoding="utf-8")
            self.assertNotIn("top-secret", serialized)
            self.assertNotIn("alice:password", serialized)
            self.assertIn("<redacted-shell-command>", serialized)

    def test_envoy_binding_requires_shared_network_and_router_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "envoy.yaml"
            config.write_text(
                "http_filters:\n"
                "- name: envoy.filters.http.ext_proc\n"
                "  typed_config:\n"
                "    grpc_service:\n"
                "      envoy_grpc:\n"
                "        cluster_name: active_extproc\n"
                "clusters:\n"
                "- name: active_extproc\n"
                "  load_assignment:\n"
                "    endpoints:\n"
                "    - socket_address:\n"
                "        address: router\n"
                "- name: unused\n"
                "  load_assignment:\n"
                "    endpoints:\n"
                "    - socket_address:\n"
                "        address: other-router\n",
                encoding="utf-8",
            )
            router = self.inspect()
            router["NetworkSettings"] = {"Networks": {
                "bench": {"IPAddress": "172.20.0.3", "Aliases": ["router"]}
            }}
            envoy = self.inspect()
            envoy["NetworkSettings"] = {"Networks": {
                "bench": {"IPAddress": "172.20.0.2", "Aliases": ["envoy"]}
            }}
            envoy["Config"] = {"Entrypoint": ["envoy"], "Cmd": ["-c", "/etc/envoy/envoy.yaml"],
                               "Env": [], "Labels": {}}
            envoy["Mounts"] = [{"Source": str(config), "Destination": "/etc/envoy/envoy.yaml",
                                 "Type": "bind"}]
            with patch.object(verify_vsr_config, "inspect_container", return_value=envoy):
                binding = verify_vsr_config.verify_envoy_binding("router", router, "envoy")
            self.assertEqual(binding["mode"], "envoy-config-reference")
            self.assertEqual(binding["matched_router_identity"], "router")
            self.assertEqual(binding["active_extproc_target"], "active_extproc")

            config.write_text(config.read_text(encoding="utf-8").replace(
                "address: router", "address: unmeasured-router", 1
            ), encoding="utf-8")
            with patch.object(verify_vsr_config, "inspect_container", return_value=envoy), \
                 self.assertRaisesRegex(SystemExit, "could not prove"):
                verify_vsr_config.verify_envoy_binding("router", router, "envoy")

    def test_opaque_config_requires_exact_reviewed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "router.yaml"
            config.write_text("classifier: proprietary\n", encoding="utf-8")
            digest = hashlib.sha256(config.read_bytes()).hexdigest()
            output = root / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router", "--profile", "ngram",
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
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router", "--profile", "intent",
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ):
                verify_vsr_config.main()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(result["automatic_detection"])
            self.assertTrue(result["intent_identity_requirements"]["mmbert_32k_marker"])

    def test_unknown_classifier_cannot_be_masked_by_intent_model_identity(self) -> None:
        inspected = self.inspect()
        inspected["Config"] = {
            "Entrypoint": ["router"],
            "Cmd": ["--classifier", "proprietary", "--model", "mmBERT-32K",
                    "--adapter", "intent-LoRA"],
            "Env": [], "Labels": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router", "--profile", "intent",
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ), self.assertRaisesRegex(SystemExit, "reviewed configuration contract"):
                verify_vsr_config.main()


if __name__ == "__main__":
    unittest.main()
