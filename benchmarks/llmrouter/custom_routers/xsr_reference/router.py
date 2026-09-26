"""Thin LLMRouter plugin wrapper around the XSR reference adapter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import torch.nn as nn
from llmrouter.models.meta_router import MetaRouter


INTEGRATION_DIR = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = INTEGRATION_DIR.parents[1]
for path in (REPOSITORY_ROOT, INTEGRATION_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from xsr_router import XSRRoutingAdapter  # noqa: E402


class XSRReferenceRouter(MetaRouter):
    """Expose XSR/VSR-equivalent routing through LLMRouter's plugin API."""

    def __init__(self, yaml_path: str):
        # LLMRouter requires an nn.Module, but the reference computation is
        # intentionally the existing CPU implementation rather than a new model.
        super().__init__(model=nn.Identity())
        self.adapter = XSRRoutingAdapter.from_config(Path(yaml_path))

    def route_single(self, query_input: dict[str, Any]) -> dict[str, Any]:
        return self.adapter.route(query_input)

    def route_batch(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.route_single(query_input) for query_input in batch]
