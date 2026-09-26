#!/usr/bin/env python3
"""Small, untimed concurrent marker-backend validation for paper runs."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import urllib.request


CASES = (
    ("coding", "write a python function"),
    ("math", "calculate the derivative of x squared"),
    ("qa", "answer this question: what is the capital of France?"),
    ("writing", "write a short poem about rain"),
    ("others", "tell me a short story"),
)


def request(url: str, expected: str, prompt: str, timeout_s: float) -> None:
    body = json.dumps({"model": "MoM", "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        payload = response.read().decode("utf-8", errors="replace")
    if f'"backend":"{expected}"' not in payload:
        raise RuntimeError(f"expected backend {expected}, got: {payload}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--timeout-s", type=float, default=10)
    args = parser.parse_args()
    cases = CASES * args.rounds
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(request, args.url, route, prompt, args.timeout_s) for route, prompt in cases]
        for future in futures:
            future.result()
    print(f"Untimed load validation passed: {len(cases)} requests to {args.url}")


if __name__ == "__main__":
    main()
