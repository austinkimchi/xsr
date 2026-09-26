#!/usr/bin/env python3
"""Run the pinned LLMRouter server without per-request console I/O."""

from __future__ import annotations

import argparse
import builtins
import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

import uvicorn
from openclaw_router import OpenClawConfig, create_app

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.llmrouter.xsr_router import (
    XSRRoutingAdapter,
    configured_method,
    configured_path,
)


FULL_PROMPT_METHODS = {"ngram", "bm25"}
UPSTREAM_TRUNCATION = "normalize_content(raw_content)[:500]"
MARKER_BACKENDS = {
    "coding": "http://127.0.0.1:18391",
    "math": "http://127.0.0.1:18392",
    "others": "http://127.0.0.1:18393",
    "qa": "http://127.0.0.1:18394",
    "writing": "http://127.0.0.1:18395",
}
PER_REQUEST_LOG_PREFIXES = (
    "[Media] Processed:",
    "[Router] Query:",
    "[Router] Rule matched:",
    "[Router] Strategy=",
    "[Router] Using default:",
    "[Specified] Query:",
    "[WS Router] Query:",
)


class _FullPromptRoutingText(str):
    """Preserve text across OpenClaw's pinned routing-only 500-char slice."""

    def __getitem__(self, key: object) -> str:
        if key == slice(None, 500, None):
            return str(self)
        return super().__getitem__(key)  # type: ignore[arg-type]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_benchmark_configuration(config: Any, router_config: Path) -> dict[str, Any]:
    """Fail closed if the baseline could execute anything but the intended path."""
    router_config = router_config.resolve()
    method = configured_method(router_config)
    adapter = XSRRoutingAdapter.from_config(router_config)

    if config.router.strategy != "llmrouter" or config.router.llmrouter_name != "xsr_reference":
        raise RuntimeError("benchmark requires the xsr_reference LLMRouter strategy")
    if config.router.llmrouter_model_path:
        raise RuntimeError("xsr_reference benchmark must not configure an upstream model path")
    if getattr(config.memory, "enabled", False):
        raise RuntimeError("benchmark must not enable OpenClaw routing memory")
    if getattr(config.media, "enabled", False):
        raise RuntimeError("benchmark must not enable OpenClaw media processing")

    actual_backends = {
        name: item.base_url.rstrip("/") for name, item in config.llms.items()
    }
    if actual_backends != MARKER_BACKENDS:
        raise RuntimeError(
            f"benchmark backends must be the local marker set; found {actual_backends}"
        )
    for name, item in config.llms.items():
        if item.provider != "local" or item.auth_mode != "none" or item.model_id != name:
            raise RuntimeError(f"benchmark backend {name!r} is not a local unauthenticated marker")

    metadata: dict[str, Any] = {
        "schema": "xsr-llmrouter-benchmark-runtime-v1",
        "router": "xsr_reference",
        "router_config": str(router_config),
        "router_config_sha256": _sha256(router_config),
        "method": method,
        "memory_enabled": False,
        "media_enabled": False,
        "marker_backends": actual_backends,
        "uvicorn_workers": 1,
    }
    if method in FULL_PROMPT_METHODS:
        if os.environ.get("XSR_DISTILL_MODEL"):
            raise RuntimeError(
                f"{method} benchmark requires XSR_DISTILL_MODEL to be unset"
            )
        if adapter.model is not None:
            raise RuntimeError(f"{method} benchmark unexpectedly loaded an inference model")
        route_methods = {str(route["method"]).lower() for route in adapter.routes}
        if route_methods != {method}:
            raise RuntimeError(
                f"{method} benchmark contains other request-time signals: {route_methods}"
            )
        policy_path = configured_path(router_config, "policy")
        if policy_path is None:
            raise RuntimeError(f"{method} benchmark has no policy")
        metadata.update(
            {
                "policy": str(policy_path),
                "policy_sha256": _sha256(policy_path),
                "request_time_signals": [method],
                "inference_model": "not-applicable",
                "xsr_distill_model_env": "unset",
            }
        )
    return metadata


def validate_benchmark_runtime(app: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    """Verify the plugin instance which the timed FastAPI endpoint closes over."""
    endpoint = next(
        (
            route.endpoint
            for route in app.routes
            if getattr(route, "path", None) == "/v1/chat/completions"
        ),
        None,
    )
    if endpoint is None:
        raise RuntimeError("pinned OpenClaw chat endpoint was not found")
    closure = inspect.getclosurevars(endpoint).nonlocals
    router = closure.get("router")
    llmrouter_adapter = getattr(router, "_llmrouter_adapter", None)
    plugin = getattr(llmrouter_adapter, "router", None)
    reference = getattr(plugin, "adapter", None)

    import torch.nn as nn

    if not isinstance(getattr(plugin, "model", None), nn.Identity):
        raise RuntimeError("xsr_reference MetaRouter placeholder is not nn.Identity")
    if getattr(reference, "method", None) != metadata["method"]:
        raise RuntimeError("loaded xsr_reference method does not match the selected config")
    if metadata["method"] in FULL_PROMPT_METHODS and getattr(reference, "model", None) is not None:
        raise RuntimeError("loaded keyword reference unexpectedly contains an inference model")

    metadata.update(
        {
            "plugin_class": f"{type(plugin).__module__}.{type(plugin).__name__}",
            "reference_adapter_class": (
                f"{type(reference).__module__}.{type(reference).__name__}"
            ),
            "meta_router_placeholder": "torch.nn.Identity",
            "inference_model_loaded": getattr(reference, "model", None) is not None,
        }
    )
    return metadata


def _is_per_request_log(message: object) -> bool:
    text = str(message)
    stripped = text.strip()
    return bool(stripped) and (
        set(stripped) == {"="} or text.startswith(PER_REQUEST_LOG_PREFIXES)
    )


def install_benchmark_log_filter() -> None:
    """Suppress pinned OpenClaw request diagnostics without changing upstream."""
    import openclaw_router.routers as routers
    import openclaw_router.server as server

    original_print = getattr(server, "print", builtins.print)
    original_safe_log = routers._safe_log

    def benchmark_print(*values: object, **kwargs: object) -> None:
        if values and _is_per_request_log(values[0]):
            return
        original_print(*values, **kwargs)

    def benchmark_safe_log(message: object) -> None:
        if _is_per_request_log(message):
            return
        original_safe_log(message)

    # The public create_app symbol is a lazy wrapper. Patch the two modules in
    # which the pinned request handlers and select_model method resolve globals.
    server.print = benchmark_print  # type: ignore[attr-defined]
    server._safe_log = benchmark_safe_log
    routers._safe_log = benchmark_safe_log


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

    metadata = validate_benchmark_configuration(config, Path(args.router_config))
    app = create_benchmark_app(config)
    validate_benchmark_runtime(app, metadata)
    install_benchmark_log_filter()
    builtins.print(
        f"[XSR benchmark metadata] {json.dumps(metadata, sort_keys=True)}",
        flush=True,
    )
    uvicorn.run(app, host=config.host, port=config.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
