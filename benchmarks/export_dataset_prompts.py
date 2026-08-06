#!/usr/bin/env python3
"""Export dataset prompts to JSONL format for wrk/wrk2 Lua benchmarks."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from types import SimpleNamespace
from pathlib import Path
import socket
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

from benchmark_keyword_routing import (
    DATASETS,
    DEFAULT_CACHE_DIR,
    ROUTES,
    chat_body,
    load_cases,
    load_policy,
    validate_policy,
)


ROUTE_KEYS = {
    "c": "coding",
    "coding": "coding",
    "m": "math",
    "math": "math",
    "o": "others",
    "other": "others",
    "others": "others",
}

DEFAULT_AI_ENDPOINT = "https://akim5-7179-resource.services.ai.azure.com/openai/v1"
DEFAULT_AI_MODEL = "gpt-5-mini"


def is_word_char(value: str) -> bool:
    return value.isalnum() or value == "_"


def keyword_matches(
    prompt: str,
    routes: list[dict[str, object]],
    case_sensitive: bool,
) -> list[tuple[str, str, bool]]:
    text = prompt if case_sensitive else prompt.lower()
    matches: list[tuple[str, str, bool]] = []
    for route in routes:
        route_name = str(route["name"])
        for keyword in route["keywords"]:  # type: ignore[index]
            token = str(keyword) if case_sensitive else str(keyword).lower()
            start = text.find(token)
            if start < 0:
                continue
            end = start + len(token)
            left_partial = start > 0 and is_word_char(text[start - 1])
            right_partial = end < len(text) and is_word_char(text[end])
            matches.append((route_name, token, left_partial or right_partial))
    return matches


def ambiguity_reason(matches: list[tuple[str, str, bool]]) -> str | None:
    route_names = {route for route, _, _ in matches}
    if len(route_names) > 1:
        return "matches multiple routes"
    if any(partial for _, _, partial in matches):
        return "contains a substring keyword match"
    return None


def prompt_preview(prompt: str, max_chars: int = 1200) -> str:
    normalized = " ".join(prompt.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3] + "..."


def ask_route(index: int, total: int, prompt: str, suggested: str, reason: str,
              matches: list[tuple[str, str, bool]]) -> str | None:
    print("\n" + "=" * 78)
    print(f"Prompt {index}/{total}: {reason}")
    print(f"Suggested route: {suggested}")
    if matches:
        rendered = ", ".join(
            f"{route}:{keyword}{'*' if partial else ''}"
            for route, keyword, partial in matches
        )
        print(f"Keyword matches: {rendered}")
        print("* means substring-only match inside a larger word")
    print("\n" + prompt_preview(prompt))
    while True:
        choice = input(
            "\nRoute [c]oding/[m]ath/[o]thers/[k]eep/[s]kip/[q]uit: "
        ).strip().lower()
        if choice in {"", "k", "keep"}:
            return suggested
        if choice in {"s", "skip"}:
            return None
        if choice in {"q", "quit"}:
            raise SystemExit("label review cancelled")
        route = ROUTE_KEYS.get(choice)
        if route:
            return route
        print("Please enter c, m, o, k, s, or q.")


def response_text(response: dict[str, object]) -> str:
    text = response.get("output_text")
    if isinstance(text, str):
        return text
    chunks: list[str] = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    return "".join(chunks)


def parse_ai_route(text: str) -> str:
    stripped = text.strip()
    try:
        data = json.loads(stripped)
        route = data.get("route")
        if isinstance(route, str) and route.lower() in ROUTE_KEYS:
            return ROUTE_KEYS[route.lower()]
    except json.JSONDecodeError:
        pass
    lowered = stripped.lower()
    for route in ROUTES:
        if lowered == route or f'"{route}"' in lowered:
            return route
    raise ValueError(f"AI response did not contain a valid route: {text!r}")


def ai_label_prompt(
    prompt: str,
    endpoint: str,
    model: str,
    api_key: str,
    timeout_s: float,
) -> str:
    instructions = (
        "Classify the prompt into exactly one route for an LLM router.\n"
        "coding: writing, debugging, explaining, optimizing, or reviewing code, "
        "software systems, algorithms, APIs, CLIs, infrastructure, kernels, or security engineering.\n"
        "math: solving, calculating, deriving, proving, or tutoring mathematics, statistics, "
        "formal quantitative reasoning, equations, matrices, probability, geometry, physics, or chemistry calculations.\n"
        "others: anything else, including philosophy, history, writing, roleplay, planning, general advice, or non-technical creative work.\n"
        "Return JSON only in this exact shape: {\"route\":\"coding|math|others\"}."
    )
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": instructions}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        ],
    }
    request_body = json.dumps(payload).encode("utf-8")
    url = endpoint.rstrip("/") + "/responses"
    for attempt in range(6):
        try:
            request = urllib.request.Request(
                url,
                data=request_body,
                headers={
                    "Content-Type": "application/json",
                    "api-key": api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return parse_ai_route(response_text(json.load(response)))
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == 5:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"AI label request failed with HTTP {exc.code}: {body}") from exc
            retry_after = exc.headers.get("Retry-After")
            try:
                sleep_s = float(retry_after) if retry_after else 2**attempt
            except ValueError:
                sleep_s = 2**attempt
            print(f"AI label request rate limited/temporary failure; retrying in {sleep_s:.1f}s...", file=sys.stderr)
            time.sleep(sleep_s)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            if attempt == 5:
                raise RuntimeError(f"AI label request failed after retries: {exc}") from exc
            sleep_s = 2**attempt
            print(f"AI label request timed out/failed; retrying in {sleep_s:.1f}s...", file=sys.stderr)
            time.sleep(sleep_s)
    raise RuntimeError("AI label request failed without returning a route")


def ai_label_cases(
    cases: list[object],
    endpoint: str,
    model: str,
    api_key: str,
    timeout_s: float,
    workers: int,
) -> list[str]:
    labels: list[str | None] = [None] * len(cases)
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                ai_label_prompt,
                case.prompt,
                endpoint,
                model,
                api_key,
                timeout_s,
            ): index
            for index, case in enumerate(cases)
        }
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            labels[index] = future.result()
            completed += 1
            if completed % 10 == 0 or completed == len(cases):
                print(f"AI labeled {completed}/{len(cases)} prompts...", file=sys.stderr)
    return [label for label in labels if label is not None]


def main() -> None:
    parser = argparse.ArgumentParser(description="Export dataset prompts to JSONL")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "dataset_prompts.jsonl")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "policy_ngram.yaml")
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="supralabs")
    parser.add_argument("--scan-limit", type=int, default=2000)
    parser.add_argument("--per-route", type=int, default=50)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument(
        "--labeler",
        choices=("keyword", "ai"),
        default="keyword",
        help="Source for x_expected_route labels.",
    )
    parser.add_argument("--ai-endpoint", default=os.getenv("AZURE_OPENAI_ENDPOINT", DEFAULT_AI_ENDPOINT))
    parser.add_argument("--ai-model", default=os.getenv("AZURE_OPENAI_MODEL", DEFAULT_AI_MODEL))
    parser.add_argument("--ai-api-key-env", default="AZURE_OPENAI_API_KEY")
    parser.add_argument("--ai-timeout-s", type=float, default=60.0)
    parser.add_argument("--ai-workers", type=int, default=8, help="Concurrent AI labeling requests.")
    parser.add_argument(
        "--review-labels",
        choices=("none", "ambiguous", "all"),
        default="none",
        help="Interactively confirm no labels, only ambiguous labels, or every label.",
    )
    args = parser.parse_args()

    bench_args = SimpleNamespace(
        cache_dir=args.cache_dir,
        config=args.config,
        dataset=args.dataset,
        per_route=args.per_route,
        scan_limit=args.scan_limit,
    )

    cases, _, _ = load_cases(bench_args)
    policy = load_policy(args.config)
    case_sensitive, routes = validate_policy(policy)
    api_key = os.getenv(args.ai_api_key_env)
    if args.labeler == "ai" and not api_key:
        raise SystemExit(f"--labeler ai requires ${args.ai_api_key_env}")
    if args.ai_workers < 1:
        raise SystemExit("--ai-workers must be at least 1")
    ai_labels: list[str] = []
    if args.labeler == "ai":
        print(
            f"AI labeling {len(cases)} prompts with {args.ai_workers} workers...",
            file=sys.stderr,
        )
        ai_labels = ai_label_cases(
            cases,
            args.ai_endpoint,
            args.ai_model,
            api_key,
            args.ai_timeout_s,
            args.ai_workers,
        )

    reviewed_cases: list[tuple[object, str]] = []
    ai_count = 0
    review_count = 0
    skip_count = 0
    if args.review_labels != "none" and not sys.stdin.isatty():
        raise SystemExit("--review-labels requires an interactive terminal")
    for index, case in enumerate(cases, start=1):
        label: str | None = case.expected_route
        if args.labeler == "ai":
            ai_count += 1
            label = ai_labels[index - 1]
        matches = keyword_matches(case.prompt, routes, case_sensitive)
        reason = ambiguity_reason(matches)
        should_review = args.review_labels == "all" or (
            args.review_labels == "ambiguous" and reason is not None
        )
        if should_review:
            review_count += 1
            label = ask_route(index, len(cases), case.prompt, label, reason or "manual review", matches)
        if label is None:
            skip_count += 1
            continue
        reviewed_cases.append((case, label))

    with args.output.open("w", encoding="utf-8") as f:
        for case, label in reviewed_cases:
            body = json.loads(chat_body(case.prompt))
            body["x_expected_route"] = label
            f.write(json.dumps(body, separators=(",", ":")) + "\n")

    labels = [label for _, label in reviewed_cases]
    counts = {route: labels.count(route) for route in ROUTES}
    print(
        f"Successfully exported {len(reviewed_cases)} prompts to {args.output} "
        f"(labeler={args.labeler}, ai_labeled={ai_count}, reviewed={review_count}, "
        f"skipped={skip_count}, coding={counts['coding']}, "
        f"math={counts['math']}, others={counts['others']})"
    )

if __name__ == "__main__":
    main()
