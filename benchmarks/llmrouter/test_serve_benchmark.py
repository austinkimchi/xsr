from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("serve_benchmark.py")


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

        calls: list[tuple[object, dict[str, object]]] = []
        uvicorn = types.ModuleType("uvicorn")
        uvicorn.run = lambda app, **kwargs: calls.append((app, kwargs))

        with mock.patch.dict(sys.modules, {"openclaw_router": openclaw, "uvicorn": uvicorn}):
            spec = importlib.util.spec_from_file_location("serve_benchmark_test_module", SCRIPT)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            argv = [
                str(SCRIPT), "--config", "serve.yaml", "--router", "xsr_reference",
                "--router-config", "ngram.yaml", "--host", "0.0.0.0", "--port", "18083",
            ]
            with mock.patch.object(sys, "argv", argv):
                module.main()

        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 18083)
        self.assertFalse(config.show_model_prefix)
        self.assertEqual(config.router.strategy, "llmrouter")
        self.assertEqual(config.router.llmrouter_name, "xsr_reference")
        self.assertEqual(config.router.llmrouter_config, "ngram.yaml")
        self.assertEqual(calls[0][1]["access_log"], False)
        self.assertEqual(calls[0][1]["log_level"], "warning")


if __name__ == "__main__":
    unittest.main()
