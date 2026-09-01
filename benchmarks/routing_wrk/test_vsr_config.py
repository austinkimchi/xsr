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
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.binding_config = Path(self.temporary.name) / "envoy.yaml"
        self.binding_config.write_text(
            "static_resources:\n"
            "  listeners:\n"
            "  - name: measured\n"
            "    address:\n"
            "      socket_address:\n"
            "        address: 0.0.0.0\n"
            "        port_value: 8899\n"
            "    http_filters:\n"
            "    - name: envoy.filters.http.ext_proc\n"
            "      typed_config:\n"
            "        grpc_service:\n"
            "          google_grpc:\n"
            "            target_uri: 127.0.0.1:50051\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def binding_cmd(self, *values: str) -> list[str]:
        return ["-c", "/etc/envoy/envoy.yaml", *values]

    def listener_config(self, listeners: list[tuple[str, int, str | None]]) -> str:
        lines = ["static_resources:", "  listeners:"]
        for name, port, target in listeners:
            lines.extend([
                f"  - name: {name}",
                "    address:",
                "      socket_address:",
                "        address: 0.0.0.0",
                f"        port_value: {port}",
            ])
            if target is None:
                lines.append("    http_filters: []")
            else:
                lines.extend([
                    "    http_filters:",
                    "    - name: envoy.filters.http.ext_proc",
                    "      typed_config:",
                    "        grpc_service:",
                    "          google_grpc:",
                    f"            target_uri: {target}",
                ])
        return "\n".join(lines) + "\n"

    def run_listener_case(
        self, listeners: list[tuple[str, int, str | None]], reviewed: bool = False,
    ) -> dict[str, object]:
        self.binding_config.write_text(self.listener_config(listeners), encoding="utf-8")
        inspected = self.inspect()
        inspected["Config"]["Cmd"].extend(["--classifier", "ngram"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router",
                    "--envoy-container", "router", "--envoy-port", "8899",
                    "--profile", "ngram", "--output", str(output)]
            if reviewed:
                config = root / "reviewed.yaml"
                config.write_text("classifier: proprietary\n", encoding="utf-8")
                argv.extend(["--config", str(config),
                             "--expected-sha256", hashlib.sha256(config.read_bytes()).hexdigest(),
                             "--asserted-profile", "ngram"])
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ):
                verify_vsr_config.main()
            return json.loads(output.read_text(encoding="utf-8"))

    def inspect(self) -> dict[str, object]:
        return {
            "Image": "sha256:image",
            "Config": {"Entrypoint": ["router"], "Cmd": self.binding_cmd(),
                       "Env": [], "Labels": {}},
            "Mounts": [{"Source": str(self.binding_config),
                        "Destination": "/etc/envoy/envoy.yaml", "Type": "bind"}],
        }

    def test_two_listeners_measured_listener_is_automatic(self) -> None:
        result = self.run_listener_case([
            ("measured", 8899, "127.0.0.1:50051"),
            ("unrelated", 9999, "other-router:50051"),
        ])
        self.assertEqual(result["verification_mode"], "automatic-inspection")
        self.assertTrue(result["automatic_detection"])
        self.assertEqual(result["measured_deployment_binding"]["measured_listener_port"], 8899)
        self.assertEqual(
            result["measured_deployment_binding"]["active_extproc_endpoints"][0]["endpoint"],
            "127.0.0.1:50051",
        )

    def test_unused_listener_cannot_certify_measured_listener(self) -> None:
        result = self.run_listener_case([
            ("measured", 8899, "other-router:50051"),
            ("unused-correct", 9999, "127.0.0.1:50051"),
        ], reviewed=True)
        self.assertEqual(result["verification_mode"], "caller-reviewed-hash-contract")
        self.assertFalse(result["automatic_detection"])

    def test_no_listener_matches_measured_port_falls_back(self) -> None:
        result = self.run_listener_case([
            ("other", 9999, "127.0.0.1:50051"),
        ], reviewed=True)
        self.assertEqual(result["verification_mode"], "caller-reviewed-hash-contract")
        self.assertFalse(result["automatic_detection"])

    def test_duplicate_measured_port_falls_back(self) -> None:
        result = self.run_listener_case([
            ("first", 8899, "127.0.0.1:50051"),
            ("second", 8899, "127.0.0.1:50051"),
        ], reviewed=True)
        self.assertEqual(result["verification_mode"], "caller-reviewed-hash-contract")
        self.assertFalse(result["automatic_detection"])

    def test_single_measured_listener_remains_automatic(self) -> None:
        result = self.run_listener_case([
            ("paper", 8899, "127.0.0.1:50051"),
        ])
        self.assertEqual(result["verification_mode"], "automatic-inspection")
        self.assertTrue(result["automatic_detection"])

    def test_automatic_bm25_configuration_records_identity_without_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "router.yaml"
            config.write_text("classifier: bm25\n", encoding="utf-8")
            output = root / "run" / "vsr-verification.json"
            inspected = self.inspect()
            inspected["Config"]["Cmd"].extend(["--router-config", "/config/router.yaml"])
            inspected["Mounts"].append(
                {"Source": str(config), "Destination": "/config/router.yaml", "Type": "bind"}
            )
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "bm25",
                    "--config", str(config), "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ):
                verify_vsr_config.main()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["verification_mode"], "automatic-inspection")
            self.assertEqual(
                result["measured_deployment_binding"]["mode"],
                "same-container-active-extproc",
            )
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
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "bm25",
                    "--config", str(config), "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=self.inspect()
            ), self.assertRaisesRegex(SystemExit, "reviewed configuration contract"):
                verify_vsr_config.main()

    def test_supplied_config_inside_mounted_directory_is_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_dir = Path(temporary) / "configs"
            config_dir.mkdir()
            config = config_dir / "router.yaml"
            config.write_text("classifier: bm25\n", encoding="utf-8")
            output = Path(temporary) / "run" / "vsr-verification.json"
            inspected = self.inspect()
            inspected["Config"]["Cmd"].extend(["--router-config", "/etc/router/router.yaml"])
            inspected["Mounts"].append(
                {"Source": str(config_dir), "Destination": "/etc/router", "Type": "bind"}
            )
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "bm25", "--config", str(config),
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ):
                verify_vsr_config.main()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["verification_mode"], "automatic-inspection")

    def test_informational_labels_are_not_classifier_evidence(self) -> None:
        inspected = self.inspect()
        inspected["Config"]["Labels"] = {"classifier": "bm25"}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "bm25", "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
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
            inspected["Config"]["Cmd"].extend(["--router-config", "/configs/bm25/router.yaml"])
            inspected["Mounts"].append(
                {"Source": str(config), "Destination": "/configs/bm25/router.yaml", "Type": "bind"}
            )
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "bm25",
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
            inspected["Config"]["Cmd"].extend(["--router-config", "/config/router.yaml"])
            inspected["Mounts"].append(
                {"Source": str(config), "Destination": "/config/router.yaml", "Type": "bind"}
            )
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "bm25",
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ), self.assertRaisesRegex(SystemExit, "reviewed configuration contract"):
                verify_vsr_config.main()

    def test_runtime_identity_retains_only_minimal_provenance(self) -> None:
        inspected = self.inspect()
        inspected["Config"] = {
            "Entrypoint": ["router"],
            "Cmd": self.binding_cmd("--classifier", "bm25", "--api-key", "top-secret",
                                    "--endpoint=https://user:pass@example.test/path?token=secret"
                                    "#access_token=fragment-secret"),
            "Env": ['ROUTER_CONFIG={"endpoint":"https://env-user:env-pass@example.test"}'],
            "Labels": {"router.config": "endpoint=https://label-user:label-pass@example.test"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "bm25",
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ):
                verify_vsr_config.main()
            serialized = output.read_text(encoding="utf-8")
            self.assertNotIn("top-secret", serialized)
            self.assertNotIn("user:pass", serialized)
            self.assertNotIn("token=secret", serialized)
            self.assertNotIn("fragment-secret", serialized)
            self.assertNotIn("env-user:env-pass", serialized)
            self.assertNotIn("label-user:label-pass", serialized)
            result = json.loads(serialized)
            identity = result["runtime_identity"]
            self.assertEqual(identity["environment_variable_names"], ["ROUTER_CONFIG"])
            self.assertEqual(identity["label_names"], ["router.config"])
            self.assertEqual(len(identity["argv_sha256"]), 64)
            self.assertNotIn("cmd", identity)

    def test_runtime_identity_hashes_shell_form_command(self) -> None:
        inspected = self.inspect()
        inspected["Config"] = {
            "Entrypoint": ["sh", "-c"],
            "Cmd": self.binding_cmd("--classifier", "bm25",
                                    "router --classifier bm25 --token top-secret",
                                    "router --endpoint https://alice:password@example.test"),
            "Env": [], "Labels": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "bm25", "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ):
                verify_vsr_config.main()
            serialized = output.read_text(encoding="utf-8")
            self.assertNotIn("top-secret", serialized)
            self.assertNotIn("alice:password", serialized)
            self.assertEqual(len(json.loads(serialized)["runtime_identity"]["argv_sha256"]), 64)

    def test_envoy_binding_requires_shared_network_and_router_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "envoy.yaml"
            config.write_text(
                "static_resources:\n"
                "  listeners:\n"
                "  - name: measured\n"
                "    address:\n"
                "      socket_address:\n"
                "        address: 0.0.0.0\n"
                "        port_value: 8899\n"
                "    http_filters:\n"
                "    - name: envoy.filters.http.ext_proc\n"
                "      typed_config:\n"
                "        grpc_service:\n"
                "          envoy_grpc:\n"
                "            cluster_name: active_extproc\n"
                "  clusters:\n"
                "  - connect_timeout: 1s\n"
                "    name: active_extproc\n"
                "    load_assignment:\n"
                "      endpoints:\n"
                "      - socket_address:\n"
                "          address: router\n"
                "  - name: unused\n"
                "    load_assignment:\n"
                "      endpoints:\n"
                "      - socket_address:\n"
                "          address: other-router\n",
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
                binding = verify_vsr_config.verify_envoy_binding("router", router, "envoy", 8899)
            self.assertEqual(binding["mode"], "envoy-config-reference")
            self.assertEqual(
                binding["active_extproc_endpoints"],
                [{"target": "active_extproc", "endpoint": "router",
                  "matched_router_identity": "router"}],
            )

            router["NetworkSettings"]["Networks"]["private"] = {
                "IPAddress": "10.0.0.3", "Aliases": ["private-router-alias"]
            }
            original = config.read_text(encoding="utf-8")
            config.write_text(
                original.replace("address: router", "address: private-router-alias", 1),
                encoding="utf-8",
            )
            with patch.object(verify_vsr_config, "inspect_container", return_value=envoy), \
                 self.assertRaisesRegex(SystemExit, "active ExtProc endpoint"):
                verify_vsr_config.verify_envoy_binding("router", router, "envoy", 8899)
            config.write_text(original, encoding="utf-8")

            config.write_text(config.read_text(encoding="utf-8").replace(
                "        address: router\n",
                "        address: router\n"
                "    - socket_address:\n"
                "        address: unverified-router\n",
                1,
            ), encoding="utf-8")
            with patch.object(verify_vsr_config, "inspect_container", return_value=envoy), \
                 self.assertRaisesRegex(SystemExit, "active ExtProc endpoint"):
                verify_vsr_config.verify_envoy_binding("router", router, "envoy", 8899)

            config.write_text(config.read_text(encoding="utf-8").replace(
                "address: router", "address: unmeasured-router", 1
            ), encoding="utf-8")
            with patch.object(verify_vsr_config, "inspect_container", return_value=envoy), \
                 self.assertRaisesRegex(SystemExit, "active ExtProc endpoint"):
                verify_vsr_config.verify_envoy_binding("router", router, "envoy", 8899)

    def test_envoy_binding_reads_image_baked_active_config(self) -> None:
        router = self.inspect()
        router["NetworkSettings"] = {"Networks": {
            "bench": {"IPAddress": "172.20.0.3", "Aliases": ["router"]}
        }}
        envoy = self.inspect()
        envoy["NetworkSettings"] = {"Networks": {
            "bench": {"IPAddress": "172.20.0.2", "Aliases": ["envoy"]}
        }}
        envoy["Config"] = {"Entrypoint": ["envoy"], "Cmd": ["--config-path=/etc/envoy/baked.yaml"],
                           "Env": [], "Labels": {}}
        envoy["Mounts"] = []
        baked = (
            "static_resources:\n"
            "  listeners:\n"
            "  - name: measured\n"
            "    address:\n"
            "      socket_address:\n"
            "        address: 0.0.0.0\n"
            "        port_value: 8899\n"
            "    http_filters:\n"
            "    - name: envoy.filters.http.ext_proc\n"
            "      typed_config:\n"
            "        grpc_service:\n"
            "          google_grpc:\n"
            "            target_uri: router:50051\n"
        )
        with patch.object(verify_vsr_config, "inspect_container", return_value=envoy), \
             patch.object(verify_vsr_config.subprocess, "check_output", return_value=baked) as read:
            binding = verify_vsr_config.verify_envoy_binding("router", router, "envoy", 8899)
        read.assert_called_once_with(
            ["docker", "exec", "envoy", "cat", "/etc/envoy/baked.yaml"],
            text=True, stderr=verify_vsr_config.subprocess.DEVNULL,
        )
        self.assertEqual(binding["active_extproc_endpoints"][0]["endpoint"], "router:50051")

    def test_opaque_config_requires_exact_reviewed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "router.yaml"
            config.write_text("classifier: proprietary\n", encoding="utf-8")
            digest = hashlib.sha256(config.read_bytes()).hexdigest()
            output = root / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "ngram",
                    "--config", str(config), "--expected-sha256", digest,
                    "--asserted-profile", "ngram", "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=self.inspect()
            ):
                verify_vsr_config.main()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["verification_mode"], "caller-reviewed-hash-contract")
            self.assertFalse(result["automatic_detection"])

    def test_ambiguous_envoy_binding_falls_back_to_reviewed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "reviewed.yaml"
            config.write_text("classifier: proprietary\n", encoding="utf-8")
            digest = hashlib.sha256(config.read_bytes()).hexdigest()
            output = Path(temporary) / "run" / "vsr-verification.json"
            self.binding_config.write_text(
                self.binding_config.read_text(encoding="utf-8").replace(
                    "127.0.0.1:50051", "unverified-router:50051"
                ),
                encoding="utf-8",
            )
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "ngram", "--config", str(config),
                    "--expected-sha256", digest, "--asserted-profile", "ngram",
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=self.inspect()
            ):
                verify_vsr_config.main()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["verification_mode"], "caller-reviewed-hash-contract")
            self.assertEqual(result["measured_deployment_binding"]["mode"], "automatic-unavailable")

    def test_intent_auto_detection_requires_mmbert_32k_and_lora(self) -> None:
        inspected = self.inspect()
        inspected["Config"] = {
            "Entrypoint": ["router"],
            "Cmd": self.binding_cmd("--model", "mmBERT-32K", "--adapter", "intent-LoRA"),
            "Env": [], "Labels": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "intent",
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
            "Cmd": self.binding_cmd("--classifier", "not-intent", "--model", "mmBERT-32K",
                                    "--adapter", "intent-LoRA"),
            "Env": [], "Labels": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run" / "vsr-verification.json"
            argv = ["verify_vsr_config.py", "--container", "router", "--envoy-container", "router",
                    "--envoy-port", "8899", "--profile", "intent",
                    "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(
                verify_vsr_config, "inspect_container", return_value=inspected
            ), self.assertRaisesRegex(SystemExit, "reviewed configuration contract"):
                verify_vsr_config.main()


if __name__ == "__main__":
    unittest.main()
