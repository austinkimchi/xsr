#!/usr/bin/env python3
"""Run the pinned LLMRouter server without per-request console I/O."""

from __future__ import annotations

import argparse
import builtins
import inspect
import sys
from pathlib import Path
from typing import Any, Callable

import uvicorn
from openclaw_router import OpenClawConfig, create_app

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.llmrouter.xsr_router import configured_method


FULL_PROMPT_METHODS = {"ngram", "bm25"}
UPSTREAM_TRUNCATION = "normalize_content(raw_content)[:500]"


class _FullPromptRoutingText(str):
    """Preserve text across OpenClaw's pinned routing-only 500-char slice."""

    def __getitem__(self, key: object) -> str:
        if key == slice(None, 500, None):
            return str(self)
        return super().__getitem__(key)  # type: ignore[arg-type]


def create_benchmark_app(
    config: Any,
    app_factory: Callable[..., Any] = create_app,
) -> Any:
    """Create the benchmark app with full prompts for deterministic XSR routers.

    Pinned OpenClaw truncates the normalized last user message immediately before
    ``OpenClawRouter.select_model``.  Returning a string subclass that ignores
    that one exact slice keeps the upstream checkout unchanged and leaves the
    request forwarded to the selected backend otherwise untouched.
    """
    router = config.router
    if router.llmrouter_name != "xsr_reference":
        return app_factory(config=config)
    method = configured_method(Path(router.llmrouter_config))
    if method not in FULL_PROMPT_METHODS:
        return app_factory(config=config)

    import openclaw_router.server as server

    source = inspect.getsource(server.create_app).replace(" ", "")
    if UPSTREAM_TRUNCATION.replace(" ", "") not in source:
        raise RuntimeError(
            "pinned OpenClaw routing truncation was not found; review the "
            "benchmark integration before using a different upstream revision"
        )

    current_normalize = server.normalize_content
    if not getattr(current_normalize, "_xsr_full_prompt", False):
        original_normalize = current_normalize

        def normalize_full_prompt(content: Any) -> str:
            return _FullPromptRoutingText(original_normalize(content))

        normalize_full_prompt._xsr_full_prompt = True  # type: ignore[attr-defined]
        server.normalize_content = normalize_full_prompt

    return app_factory(config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--router", required=True)
    parser.add_argument("--router-config", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    config = OpenClawConfig.from_yaml(args.config)
    config.host = args.host
    config.port = args.port
    config.show_model_prefix = False
    config.router.strategy = "llmrouter"
    config.router.llmrouter_name = args.router
    config.router.llmrouter_config = args.router_config

    app = create_benchmark_app(config)
    original_print = builtins.print

    def benchmark_print(*values: object, **kwargs: object) -> None:
        # The pinned server prints one routing line per request. That I/O would
        # grow an enormous log and distort the throughput path under test.
        if values and isinstance(values[0], str) and values[0].startswith("[Router] Query:"):
            return
        original_print(*values, **kwargs)

    create_app.__globals__["print"] = benchmark_print
    uvicorn.run(app, host=config.host, port=config.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
