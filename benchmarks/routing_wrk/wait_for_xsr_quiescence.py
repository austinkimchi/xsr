#!/usr/bin/env python3
"""Wait until one live XSR process has reaped every connection set."""

from __future__ import annotations

import argparse
import socket
import time
from pathlib import Path


def read_status(path: Path, timeout: float = 1.0) -> dict[str, int]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        raw = b"".join(iter(lambda: client.recv(4096), b""))
    raw = raw.decode("ascii").strip()
    values: dict[str, int] = {}
    for field in raw.split():
        key, separator, value = field.partition("=")
        if not separator:
            raise ValueError(f"invalid XSR status field: {field!r}")
        values[key] = int(value)
    required = {
        "pid",
        "active_connection_sets",
        "free_slot_sets",
        "quarantined_slot_sets",
        "accepted_total",
        "reaped_total",
        "sockmap_entries",
        "routes_entries",
        "http_flows_entries",
        "route_decisions_entries",
    }
    missing = required - values.keys()
    if missing:
        raise ValueError(f"XSR status is missing fields: {sorted(missing)}")
    return values


def wait_for_quiescence(
    path: Path, expected_pid: int, timeout: float, minimum_reaped: int = 0
) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    last_status: dict[str, int] | None = None
    while time.monotonic() < deadline:
        try:
            last_status = read_status(path)
            if last_status["pid"] != expected_pid:
                raise RuntimeError(
                    f"XSR PID changed: expected {expected_pid}, found {last_status['pid']}"
                )
            if last_status["quarantined_slot_sets"]:
                raise RuntimeError(
                    "XSR quarantined slot sets during cleanup: "
                    f"{last_status['quarantined_slot_sets']}"
                )
            if (
                last_status["active_connection_sets"] == 0
                and last_status["sockmap_entries"] == 0
                and last_status["routes_entries"] == 0
                and last_status["http_flows_entries"] == 0
                and last_status["route_decisions_entries"] == 0
                and last_status["reaped_total"] >= minimum_reaped
            ):
                return last_status
            last_error = None
        except (ConnectionError, FileNotFoundError, OSError, ValueError) as error:
            last_error = error
        time.sleep(0.02)
    detail = f"last status={last_status}" if last_status else f"last error={last_error}"
    raise TimeoutError(f"XSR did not become quiescent within {timeout:g}s; {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--minimum-reaped", type=int, default=0)
    args = parser.parse_args()
    status = wait_for_quiescence(
        args.socket, args.pid, args.timeout, args.minimum_reaped
    )
    print(" ".join(f"{key}={value}" for key, value in status.items()))


if __name__ == "__main__":
    main()
