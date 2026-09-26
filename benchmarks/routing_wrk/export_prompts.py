#!/usr/bin/env python3
"""Export dataset prompts to JSONL format for the routing benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
from types import SimpleNamespace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks"))

from routing_correctness.benchmark import (
    DATASETS,
    DEFAULT_CACHE_DIR,
    ROUTERARENA_ROWS,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Export dataset prompts to JSONL")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "dataset_prompts.jsonl")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "policy_ngram.yaml")
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="speed-bench")
    parser.add_argument(
        "--routerarena-split",
        choices=sorted(ROUTERARENA_ROWS),
        default="full",
        help="RouterArena split; ignored for other datasets (default: full).",
    )
    parser.add_argument("--scan-limit", type=int, default=2000)
    parser.add_argument("--per-route", type=int, default=50)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
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
        routerarena_split=args.routerarena_split,
        scan_limit=args.scan_limit,
    )

    cases, _, _ = load_cases(bench_args)
    policy = load_policy(args.config)
    case_sensitive, routes = validate_policy(policy)
    reviewed_cases: list[tuple[object, str]] = []
    review_count = 0
    skip_count = 0
    if args.review_labels != "none" and not sys.stdin.isatty():
        raise SystemExit("--review-labels requires an interactive terminal")
    for index, case in enumerate(cases, start=1):
        label: str | None = case.expected_route
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

    spec = DATASETS[args.dataset]
    dataset_identity = {
        "name": args.dataset,
        "repository": spec["dataset"],
        "config": spec.get("config"),
        "split": spec.get("split", args.routerarena_split),
        "revision": spec.get("revision"),
    }
    sidecar = {
        "schema_version": 1,
        "prompts_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "workload_identity": {
            "id": ":".join(str(value) for value in (
                args.dataset, dataset_identity["config"], dataset_identity["split"]
            ) if value),
            "kind": "keyword-dataset",
            "dataset": dataset_identity,
            "labeler": "keyword-policy",
        },
    }
    Path(f"{args.output.resolve()}.metadata.json").write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    labels = [label for _, label in reviewed_cases]
    counts = {route: labels.count(route) for route in ROUTES}
    rendered_counts = ", ".join(f"{route}={counts[route]}" for route in ROUTES)
    print(
        f"Successfully exported {len(reviewed_cases)} prompts to {args.output} "
        f"(labeler=keyword-policy, reviewed={review_count}, "
        f"skipped={skip_count}, {rendered_counts})"
    )

if __name__ == "__main__":
    main()
