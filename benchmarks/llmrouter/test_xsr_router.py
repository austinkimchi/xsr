from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from benchmarks.lora_distill.core import (
    CLASS_COUNT,
    DEPLOYMENT_FEATURE_COUNT,
    LABELS,
    QuantizedModel,
    feature_indices,
    integer_scores,
    predict,
    write_kernel_model,
)
from benchmarks.policy.generate_keyword_header import load_policy, validate_policy
from benchmarks.routing_correctness.benchmark import expected_route

from xsr_router import XSRRoutingAdapter, query_text


ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_DIR = Path(__file__).resolve().parent


class XSRRoutingAdapterTest(unittest.TestCase):
    def assert_policy_parity(self, config_name: str, prompts: list[str]) -> None:
        adapter = XSRRoutingAdapter.from_config(
            INTEGRATION_DIR / "configs" / config_name
        )
        policy_name = "policy_ngram.yaml" if adapter.method == "ngram" else "policy_bm25.yaml"
        case_sensitive, routes = validate_policy(load_policy(ROOT / "config" / policy_name))
        for prompt in prompts:
            with self.subTest(method=adapter.method, prompt=prompt):
                expected, keyword = expected_route(prompt, routes, case_sensitive)
                result = adapter.route({"query": prompt})
                self.assertEqual(result["model_name"], expected)
                self.assertEqual(result["predicted_llm"], expected)
                self.assertEqual(result["matched_keyword"], keyword)

    def test_ngram_matches_existing_reference(self) -> None:
        self.assert_policy_parity(
            "ngram.yaml",
            ["Please implement a function", "calculate the derivative", "unrelated greeting"],
        )

    def test_bm25_matches_existing_reference(self) -> None:
        self.assert_policy_parity(
            "bm25.yaml",
            ["Write code for this function", "solve this equation", "unrelated greeting"],
        )

    def test_openai_style_request_uses_latest_user_message(self) -> None:
        request = {
            "messages": [
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
                {"role": "user", "content": "implement this function"},
            ]
        }
        self.assertEqual(query_text(request), "implement this function")

    def test_intent_matches_frozen_integer_student_and_route_mapping(self) -> None:
        weights = np.zeros((CLASS_COUNT, DEPLOYMENT_FEATURE_COUNT), dtype=np.int8)
        bias = np.zeros(CLASS_COUNT, dtype=np.int32)
        bias[2] = 1
        for index in feature_indices(
            "kernel implementation", feature_count=DEPLOYMENT_FEATURE_COUNT
        ):
            weights[3, index] = 7
        for index in feature_indices(
            "solve equation", feature_count=DEPLOYMENT_FEATURE_COUNT
        ):
            weights[9, index] = 7
        model = QuantizedModel(weights=weights, bias=bias, scale=1.0)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.xsrf"
            write_kernel_model(path, model)
            adapter = XSRRoutingAdapter("intent", model_path=path)
            for prompt, route in (
                ("kernel implementation", "coding"),
                ("solve equation", "math"),
                ("hi", "others"),
            ):
                with self.subTest(prompt=prompt):
                    direct_id = predict(integer_scores(prompt, weights, bias))
                    result = adapter.route({"prompt": prompt})
                    self.assertEqual(result["intent_id"], direct_id)
                    self.assertEqual(result["intent"], LABELS[direct_id])
                    self.assertEqual(result["model_name"], route)


class PinnedLLMRouterPluginIntegrationTest(unittest.TestCase):
    def plugin_system_path(self) -> Path | None:
        source = os.environ.get("LLMROUTER_SOURCE")
        if source:
            return Path(source) / "llmrouter" / "plugin_system.py"
        try:
            spec = importlib.util.find_spec("llmrouter.plugin_system")
        except ModuleNotFoundError:
            return None
        return Path(spec.origin) if spec and spec.origin else None

    def test_upstream_registry_discovers_and_invokes_plugin(self) -> None:
        plugin_system_path = self.plugin_system_path()
        if plugin_system_path is None or not plugin_system_path.exists():
            self.skipTest("install the pinned optional LLMRouter dependency")

        spec = importlib.util.spec_from_file_location(
            "pinned_llmrouter_plugin_system", plugin_system_path
        )
        assert spec and spec.loader
        plugin_system = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin_system)

        meta_module = types.ModuleType("llmrouter.models.meta_router")

        class MetaRouter:
            def __init__(self, model: object, yaml_path: str | None = None) -> None:
                self.model = model

        meta_module.MetaRouter = MetaRouter
        torch_module = types.ModuleType("torch")
        nn_module = types.ModuleType("torch.nn")

        class Identity:
            pass

        nn_module.Identity = Identity
        torch_module.nn = nn_module
        modules = {
            "llmrouter.models.meta_router": meta_module,
            "torch": torch_module,
            "torch.nn": nn_module,
        }
        with mock.patch.dict(sys.modules, modules):
            registry = plugin_system.PluginRegistry()
            registry.discover_plugins(
                str(INTEGRATION_DIR / "custom_routers"), verbose=False
            )
            registered = registry.get_router("xsr_reference")
            self.assertIsNotNone(registered)
            assert registered is not None
            plugin_class, trainer_class = registered
            self.assertIsNone(trainer_class)
            router = plugin_class(str(INTEGRATION_DIR / "configs" / "ngram.yaml"))
            results = router.route_batch(
                [{"query": "implement a function"}, {"query": "ordinary greeting"}]
            )

        self.assertEqual([item["model_name"] for item in results], ["coding", "others"])

    def test_local_serve_config_preserves_route_backend_mapping(self) -> None:
        plugin_system_path = self.plugin_system_path()
        if plugin_system_path is None:
            self.skipTest("install the pinned optional LLMRouter dependency")
        config_path = plugin_system_path.parents[1] / "openclaw_router" / "config.py"
        spec = importlib.util.spec_from_file_location(
            "pinned_llmrouter_openclaw_config", config_path
        )
        assert spec and spec.loader
        config_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = config_module
        try:
            spec.loader.exec_module(config_module)
            config = config_module.OpenClawConfig.from_yaml(
                str(INTEGRATION_DIR / "configs" / "serve-local.yaml")
            )
        finally:
            sys.modules.pop(spec.name, None)

        self.assertEqual(config.router.strategy, "llmrouter")
        self.assertEqual(config.router.llmrouter_name, "xsr_reference")
        self.assertEqual(
            {name: item.base_url for name, item in config.llms.items()},
            {
                "coding": "http://127.0.0.1:18391",
                "math": "http://127.0.0.1:18392",
                "others": "http://127.0.0.1:18393",
                "qa": "http://127.0.0.1:18394",
                "writing": "http://127.0.0.1:18395",
            },
        )


if __name__ == "__main__":
    unittest.main()
