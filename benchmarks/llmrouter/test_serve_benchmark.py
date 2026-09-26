from __future__ import annotations

import importlib.util
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("serve_benchmark.py")
INTEGRATION_DIR = SCRIPT.parent


class BenchmarkServerTest(unittest.TestCase):
    def test_launcher_uses_upstream_app_without_access_logging(self) -> None:
        config = types.SimpleNamespace(
            host="127.0.0.1",
            port=8000,
            show_model_prefix=True,
            router=types.SimpleNamespace(strategy="random", llmrouter_name=None, llmrouter_config=None),
        )
        openclaw = types.ModuleType("openclaw_router")
        openclaw.OpenClawConfig = types.SimpleNamespace(from_yaml=lambda _: config)
        exec("def create_app(config):\n    return {'config': config}\n", openclaw.__dict__)
        server = types.ModuleType("openclaw_router.server")
        server.normalize_content = lambda content: str(content)
        exec("def create_app(config):\n    value = normalize_content('test')[:500]\n    return {'config': config, 'value': value}\n", server.__dict__)
        openclaw.server = server

        calls: list[tuple[object, dict[str, object]]] = []
        uvicorn = types.ModuleType("uvicorn")
        uvicorn.run = lambda app, **kwargs: calls.append((app, kwargs))

        with mock.patch.dict(
            sys.modules,
            {"openclaw_router": openclaw, "openclaw_router.server": server, "uvicorn": uvicorn},
        ):
            spec = importlib.util.spec_from_file_location("serve_benchmark_test_module", SCRIPT)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            argv = [
                str(SCRIPT), "--config", "serve.yaml", "--router", "xsr_reference",
                "--router-config", str(INTEGRATION_DIR / "configs" / "ngram.yaml"),
                "--host", "0.0.0.0", "--port", "18083",
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    module.inspect,
                    "getsource",
                    return_value="normalize_content(raw_content)[:500]",
                ),
                mock.patch.object(
                    module,
                    "validate_benchmark_configuration",
                    return_value={"method": "ngram"},
                ),
                mock.patch.object(
                    module,
                    "validate_benchmark_runtime",
                    return_value={"method": "ngram"},
                ),
                mock.patch.object(module, "install_benchmark_log_filter"),
            ):
                with redirect_stdout(io.StringIO()):
                    module.main()

        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 18083)
        self.assertFalse(config.show_model_prefix)
        self.assertEqual(config.router.strategy, "llmrouter")
        self.assertEqual(config.router.llmrouter_name, "xsr_reference")
        self.assertEqual(
            config.router.llmrouter_config,
            str(INTEGRATION_DIR / "configs" / "ngram.yaml"),
        )
        self.assertEqual(calls[0][1]["access_log"], False)
        self.assertEqual(calls[0][1]["log_level"], "warning")


class BenchmarkLogFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            spec = importlib.util.spec_from_file_location("serve_benchmark_log_test", SCRIPT)
            assert spec and spec.loader
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)
        except ImportError as error:
            raise unittest.SkipTest(f"install the pinned LLMRouter dependency: {error}")

    def test_filters_request_logs_but_preserves_startup_warnings_and_errors(self) -> None:
        server = types.ModuleType("openclaw_router.server")
        routers = types.ModuleType("openclaw_router.routers")
        original_print = mock.Mock()
        server.print = original_print
        original_safe_log = mock.Mock()
        server._safe_log = original_safe_log
        routers._safe_log = original_safe_log

        with mock.patch.dict(
            sys.modules,
            {"openclaw_router.server": server, "openclaw_router.routers": routers},
        ):
            self.module.install_benchmark_log_filter()

        server.print("============\n")
        server.print("[Router] Query: 'prompt' -> coding")
        server.print("[Media] Processed: image")
        server.print("startup complete")
        routers._safe_log("[Router] Strategy=llmrouter(xsr_reference) -> coding")
        routers._safe_log("[Router] Warning: config fallback")
        server._safe_log("[WS Router] Query: 'prompt' -> coding")
        server._safe_log("[Router] Error: backend failed")

        original_print.assert_called_once_with("startup complete")
        self.assertEqual(
            original_safe_log.call_args_list,
            [
                mock.call("[Router] Warning: config fallback"),
                mock.call("[Router] Error: backend failed"),
            ],
        )


class FullPromptServingPathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from fastapi.testclient import TestClient
            from openclaw_router import OpenClawConfig
            import openclaw_router.routers as routers
            import openclaw_router.server as server
        except ImportError as error:
            raise unittest.SkipTest(f"install the pinned LLMRouter dependency: {error}")

        spec = importlib.util.spec_from_file_location("serve_benchmark_full_prompt_test", SCRIPT)
        assert spec and spec.loader
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.TestClient = TestClient
        cls.OpenClawConfig = OpenClawConfig
        cls.routers = routers
        cls.server = server

    def assert_prompt_reaches_xsr_reference(self, method: str, prompt: str) -> None:
        captured: list[str] = []
        upstream_adapter = self.routers.LLMRouterAdapter

        class CapturingLLMRouterAdapter(upstream_adapter):
            def __init__(self, router_name: str, **kwargs: object) -> None:
                if router_name != "xsr_reference":
                    raise AssertionError("request did not use xsr_reference")
                super().__init__(router_name, **kwargs)

            def route(self, query: str, available_models: list[str]) -> str:
                captured.append(query)
                return super().route(query, available_models)

        class FakeBackend:
            def __init__(self, config: object) -> None:
                self.config = config

            async def call(self, *_: object, **__: object) -> dict[str, object]:
                return {"choices": [{"message": {"content": "ok"}}]}

        config = self.OpenClawConfig.from_yaml(
            str(INTEGRATION_DIR / "configs" / "serve-local.yaml")
        )
        config.router.strategy = "llmrouter"
        config.router.llmrouter_name = "xsr_reference"
        config.router.llmrouter_config = str(INTEGRATION_DIR / "configs" / f"{method}.yaml")

        with (
            mock.patch.dict(
                "os.environ",
                {
                    "LLMROUTER_PLUGINS": str(INTEGRATION_DIR / "custom_routers"),
                    "XSR_DISTILL_MODEL": "",
                },
            ),
            mock.patch.object(self.routers, "LLMRouterAdapter", CapturingLLMRouterAdapter),
            mock.patch.object(self.server, "LLMBackend", FakeBackend),
        ):
            metadata = self.module.validate_benchmark_configuration(
                config, INTEGRATION_DIR / "configs" / f"{method}.yaml"
            )
            app = self.module.create_benchmark_app(config)
            metadata = self.module.validate_benchmark_runtime(app, metadata)
            response = self.TestClient(app).post(
                "/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": prompt}]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"], "coding")
        self.assertEqual(captured, [prompt])
        self.assertEqual(metadata["request_time_signals"], [method])
        self.assertEqual(metadata["inference_model"], "not-applicable")
        self.assertFalse(metadata["inference_model_loaded"])
        self.assertEqual(metadata["meta_router_placeholder"], "torch.nn.Identity")

    def test_ngram_match_after_character_500_reaches_router_intact(self) -> None:
        prompt = "neutral filler " * 40 + "implement"
        self.assertGreater(prompt.index("implement"), 500)
        self.assert_prompt_reaches_xsr_reference("ngram", prompt)

    def test_bm25_term_after_character_500_reaches_router_intact(self) -> None:
        prompt = "neutral filler " * 40 + "code"
        self.assertGreater(prompt.index("code"), 500)
        self.assert_prompt_reaches_xsr_reference("bm25", prompt)

    def test_short_prompt_reaches_router_unchanged(self) -> None:
        self.assert_prompt_reaches_xsr_reference("ngram", "please implement this")

    def test_real_http_routing_path_emits_no_request_diagnostics(self) -> None:
        class FakeBackend:
            def __init__(self, config: object) -> None:
                self.config = config

            async def call(self, *_: object, **__: object) -> dict[str, object]:
                return {"choices": [{"message": {"content": "ok"}}]}

        config = self.OpenClawConfig.from_yaml(
            str(INTEGRATION_DIR / "configs" / "serve-local.yaml")
        )
        config.router.strategy = "llmrouter"
        config.router.llmrouter_name = "xsr_reference"
        config.router.llmrouter_config = str(INTEGRATION_DIR / "configs" / "ngram.yaml")
        print_sink = mock.Mock()
        safe_log_sink = mock.Mock()

        with (
            mock.patch.dict(
                "os.environ",
                {
                    "LLMROUTER_PLUGINS": str(INTEGRATION_DIR / "custom_routers"),
                    "XSR_DISTILL_MODEL": "",
                },
            ),
            mock.patch.object(self.server, "LLMBackend", FakeBackend),
        ):
            app = self.module.create_benchmark_app(config)
            with (
                mock.patch.object(self.server, "print", print_sink, create=True),
                mock.patch.object(self.server, "_safe_log", safe_log_sink),
                mock.patch.object(self.routers, "_safe_log", safe_log_sink),
            ):
                self.module.install_benchmark_log_filter()
                response = self.TestClient(app).post(
                    "/v1/chat/completions",
                    json={
                        "model": "auto",
                        "messages": [{"role": "user", "content": "implement this"}],
                    },
                )

        self.assertEqual(response.status_code, 200)
        print_sink.assert_not_called()
        safe_log_sink.assert_not_called()


if __name__ == "__main__":
    unittest.main()
