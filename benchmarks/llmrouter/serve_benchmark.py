#!/usr/bin/env python3
"""Run the pinned LLMRouter server without per-request console I/O."""

from __future__ import annotations

import argparse
import builtins

import uvicorn
from openclaw_router import OpenClawConfig, create_app


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

    app = create_app(config=config)
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
