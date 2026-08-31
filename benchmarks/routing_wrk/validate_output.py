#!/usr/bin/env python3
"""Validate terminal wrk/wrk2 output without touching the timed request path."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ERROR_RE = re.compile(
    r"Socket errors:\s*connect\s+(?P<connect>\d+),\s*read\s+(?P<read>\d+),"
    r"\s*write\s+(?P<write>\d+),\s*timeout\s+(?P<timeout>\d+)",
    re.IGNORECASE,
)
HTTP_ERROR_RE = re.compile(r"Non-2xx or 3xx responses:\s*(?P<count>\d+)", re.IGNORECASE)
REQUESTS_RE = re.compile(r"(?P<count>\d+)\s+requests?\s+in\s+", re.IGNORECASE)
CONNECTIONS_RE = re.compile(
    r"\b\d+\s+threads?\s+and\s+(?P<count>\d+)\s+connections?\b",
    re.IGNORECASE,
)


def invalid_reasons(output: str) -> list[str]:
    """Return every validity failure reported by a completed wrk-style run."""
    reasons: list[str] = []
    for match in ERROR_RE.finditer(output):
        for name, value in match.groupdict().items():
            if int(value):
                reasons.append(f"{name} errors={value}")
    for match in HTTP_ERROR_RE.finditer(output):
        if int(match.group("count")):
            reasons.append(f"non-2xx/3xx responses={match.group('count')}")
    request_matches = list(REQUESTS_RE.finditer(output))
    if not request_matches:
        reasons.append("completed-request count was not reported")
    elif all(int(match.group("count")) == 0 for match in request_matches):
        reasons.append("zero completed requests")
    else:
        connection_matches = list(CONNECTIONS_RE.finditer(output))
        if connection_matches:
            completed = int(request_matches[-1].group("count"))
            connections = int(connection_matches[-1].group("count"))
            if completed < connections:
                reasons.append(
                    f"completed requests={completed} below connection count={connections}"
                )
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Captured wrk or wrk2 output")
    args = parser.parse_args()
    reasons = invalid_reasons(args.input.read_text(encoding="utf-8", errors="replace"))
    if reasons:
        print("; ".join(reasons))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
