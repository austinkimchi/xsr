#!/usr/bin/env python3
"""Dependency-light LLMRouter adapter for XSR's reference routing semantics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from benchmarks.policy.generate_keyword_header import load_policy, validate_policy
from benchmarks.routing_correctness.benchmark import expected_route


SUPPORTED_METHODS = ("ngram", "bm25", "intent")
INTENT_ROUTE_BY_ID = {3: "coding", 9: "math"}


def query_text(query_input: dict[str, Any]) -> str:
    """Extract text from LLMRouter's query dict or an OpenAI-style request."""
    query = query_input.get("query")
    if isinstance(query, str):
        return query

    prompt = query_input.get("prompt")
    if isinstance(prompt, str):
        return prompt

    messages = query_input.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                return content

    raise ValueError("query input requires a string 'query', 'prompt', or user message")


class XSRRoutingAdapter:
    """Route with the same userspace references used to validate XSR and VSR."""

    def __init__(
        self,
        method: str,
        *,
        policy_path: Path | None = None,
        model_path: Path | None = None,
    ) -> None:
        self.method = method.lower()
        if self.method not in SUPPORTED_METHODS:
            raise ValueError(f"method must be one of: {', '.join(SUPPORTED_METHODS)}")

        self.case_sensitive = False
        self.routes: list[dict[str, object]] = []
        self.model = None

        if self.method in {"ngram", "bm25"}:
            if policy_path is None:
                raise ValueError(f"{self.method} requires a policy path")
            self.case_sensitive, self.routes = validate_policy(load_policy(policy_path))
            methods = {str(route["method"]).lower() for route in self.routes}
            if methods != {self.method}:
                raise ValueError(
                    f"{self.method} adapter requires a policy containing only "
                    f"{self.method} signals; found {sorted(methods)}"
                )
        else:
            if model_path is None:
                raise ValueError("intent requires a frozen deployment model path")
            from benchmarks.lora_distill.core import read_deployment_model

            self.model = read_deployment_model(model_path)

    @classmethod
    def from_config(cls, config_path: Path) -> "XSRRoutingAdapter":
        config_path = config_path.resolve()
        config = load_policy(config_path)
        values = config.get("xsr")
        if not isinstance(values, dict):
            raise ValueError("adapter config requires an 'xsr' mapping")

        method = str(values.get("method", "")).lower()

        def configured_path(key: str, environment: str | None = None) -> Path | None:
            raw = values.get(key)
            value = str(raw) if isinstance(raw, str) and raw else ""
            if not value and environment:
                value = os.environ.get(environment, "")
            if not value:
                return None
            path = Path(value).expanduser()
            return path if path.is_absolute() else (config_path.parent / path).resolve()

        return cls(
            method,
            policy_path=configured_path("policy"),
            model_path=configured_path("model", "XSR_DISTILL_MODEL"),
        )

    def route(self, query_input: dict[str, Any]) -> dict[str, Any]:
        prompt = query_text(query_input)
        if self.method in {"ngram", "bm25"}:
            route, keyword = expected_route(prompt, self.routes, self.case_sensitive)
            return {
                "query": prompt,
                "model_name": route,
                "predicted_llm": route,
                "predicted_llm_name": route,
                "method": self.method,
                "matched_keyword": keyword,
            }

        from benchmarks.lora_distill.core import LABELS, integer_scores, predict

        assert self.model is not None
        intent_id = predict(integer_scores(prompt, self.model.weights, self.model.bias))
        route = INTENT_ROUTE_BY_ID.get(intent_id, "others")
        return {
            "query": prompt,
            "model_name": route,
            "predicted_llm": route,
            "predicted_llm_name": route,
            "method": self.method,
            "intent_id": intent_id,
            "intent": LABELS[intent_id],
        }
