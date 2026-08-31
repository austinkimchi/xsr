#!/usr/bin/env python3
"""Exercise SOCKMAP connection teardown and slot reuse in one XSR process."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import socket
import time
from pathlib import Path
from typing import Callable

from wait_for_xsr_quiescence import read_status, wait_for_quiescence


ROUTES = (
    ("coding", "write a python function"),
    ("math", "calculate the derivative of x squared"),
    ("qa", "answer this question: what is the capital of France?"),
    ("writing", "write a short poem about rain"),
    ("others", "tell me a short story"),
)


def receive_http_response(client: socket.socket) -> bytes:
    response = bytearray()
    while b"\r\n\r\n" not in response:
        chunk = client.recv(4096)
        if not chunk:
            raise RuntimeError("connection closed before HTTP response headers")
        response.extend(chunk)
    headers, body = response.split(b"\r\n\r\n", 1)
    content_length = None
    for line in headers.split(b"\r\n"):
        name, separator, value = line.partition(b":")
        if separator and name.lower() == b"content-length":
            content_length = int(value.strip())
    if content_length is None:
        raise RuntimeError("response has no Content-Length")
    while len(body) < content_length:
        chunk = client.recv(content_length - len(body))
        if not chunk:
            raise RuntimeError("connection closed before HTTP response body")
        body += chunk
    return bytes(body[:content_length])


def request_once(
    host: str,
    port: int,
    sequence: int,
    *,
    request_backend_close: bool = False,
    half_close: bool = False,
    no_response: bool = False,
    split_request: bool = False,
    before_half_close: Callable[[], None] | None = None,
) -> str:
    expected, prompt = ROUTES[sequence % len(ROUTES)]
    route_sequence = (
        f"no-response-{sequence}" if no_response else f"lifecycle-{sequence}"
    )
    body = json.dumps(
        {
            "model": "MoM",
            "messages": [{"role": "user", "content": prompt}],
            "x_route_seq": route_sequence,
        },
        separators=(",", ":"),
    ).encode()
    request = (
        f"POST /v1/chat/completions HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Content-Type: application/json\r\n"
        f"Connection: {'close' if request_backend_close else 'keep-alive'}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"x-route-seq: {route_sequence}\r\n\r\n"
    ).encode() + body
    with socket.create_connection((host, port), timeout=10) as client:
        client.settimeout(10)
        if split_request:
            client.sendall(request[:-1])
            if before_half_close:
                before_half_close()
                before_half_close = None
            # Establish an incomplete-parser marker, then put the final body
            # byte and FIN back-to-back to exercise stale-marker races.
            time.sleep(0.02)
            client.sendall(request[-1:])
        else:
            client.sendall(request)
        if half_close:
            if before_half_close:
                before_half_close()
            client.shutdown(socket.SHUT_WR)
        if no_response:
            if client.recv(1):
                raise AssertionError(f"request {sequence}: expected an empty response")
            return expected
        try:
            parsed = json.loads(receive_http_response(client))
        except Exception as error:
            raise RuntimeError(f"request {sequence}: response failed") from error
    if parsed.get("backend") != expected:
        raise AssertionError(
            f"request {sequence}: expected backend={expected}, found {parsed!r}"
        )
    if parsed.get("x_route_seq") != route_sequence:
        raise AssertionError(
            f"request {sequence}: response correlation mismatch: {parsed!r}"
        )
    return expected


def fd_count(pid: int) -> int:
    return len(list((Path("/proc") / str(pid) / "fd").iterdir()))


def wait_for_accepted(
    status_socket: Path, pid: int, minimum_accepted: int, timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = read_status(status_socket)
        if status["pid"] != pid:
            raise RuntimeError(f"XSR PID changed: expected {pid}, found {status['pid']}")
        if status["accepted_total"] >= minimum_accepted:
            return
        time.sleep(0.01)
    raise TimeoutError(f"XSR did not accept connection {minimum_accepted}")


def run_wave(host: str, port: int, start: int, count: int) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as executor:
        futures = [
            executor.submit(request_once, host, port, start + offset)
            for offset in range(count)
        ]
        for future in futures:
            future.result()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="10.10.0.1")
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--status-socket", type=Path, required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--sequential", type=int, default=3001)
    parser.add_argument("--wave-sizes", type=int, nargs="+", default=[1, 8, 64, 192])
    parser.add_argument("--wave-repeats", type=int, default=2)
    parser.add_argument("--cleanup-timeout", type=float, default=30)
    args = parser.parse_args()

    baseline = wait_for_quiescence(args.status_socket, args.pid, args.cleanup_timeout)
    baseline_fds = fd_count(args.pid)
    max_sampled_fds = baseline_fds
    sequence = 0
    expected_accepted = baseline["accepted_total"]

    for _ in ROUTES:
        expected_accepted += 1
        request_once(
            args.host,
            args.port,
            sequence,
            half_close=True,
            split_request=True,
            before_half_close=lambda expected=expected_accepted: wait_for_accepted(
                args.status_socket, args.pid, expected, args.cleanup_timeout
            ),
        )
        sequence += 1
    expected_reaped = baseline["reaped_total"] + len(ROUTES)
    after_half_close = wait_for_quiescence(
        args.status_socket, args.pid, args.cleanup_timeout, expected_reaped
    )

    expected_accepted += 1
    request_once(
        args.host,
        args.port,
        sequence,
        half_close=True,
        no_response=True,
        before_half_close=lambda: wait_for_accepted(
            args.status_socket,
            args.pid,
            expected_accepted,
            args.cleanup_timeout,
        ),
    )
    sequence += 1
    expected_reaped += 1
    after_empty_response = wait_for_quiescence(
        args.status_socket, args.pid, args.cleanup_timeout, expected_reaped
    )

    request_once(args.host, args.port, sequence, request_backend_close=True)
    sequence += 1
    expected_reaped += 1
    after_full_close = wait_for_quiescence(
        args.status_socket, args.pid, args.cleanup_timeout, expected_reaped
    )

    for sequence in range(sequence, sequence + args.sequential):
        request_once(args.host, args.port, sequence)
        if sequence % 100 == 99:
            max_sampled_fds = max(max_sampled_fds, fd_count(args.pid))
    expected_reaped += args.sequential
    after_sequential = wait_for_quiescence(
        args.status_socket, args.pid, args.cleanup_timeout, expected_reaped
    )
    sequential_fds = fd_count(args.pid)

    next_sequence = args.sequential + len(ROUTES) + 2
    wave_results: list[dict[str, object]] = []
    for size in args.wave_sizes:
        for repeat in range(args.wave_repeats):
            run_wave(args.host, args.port, next_sequence, size)
            next_sequence += size
            expected_reaped += size
            status = wait_for_quiescence(
                args.status_socket, args.pid, args.cleanup_timeout, expected_reaped
            )
            wave_results.append({"size": size, "repeat": repeat + 1, "status": status})

    request_once(
        args.host, args.port, next_sequence, request_backend_close=True
    )
    expected_reaped += 1
    final = wait_for_quiescence(
        args.status_socket, args.pid, args.cleanup_timeout, expected_reaped
    )
    final_fds = fd_count(args.pid)
    if final["free_slot_sets"] != baseline["free_slot_sets"]:
        raise AssertionError(f"slot blocks did not return to baseline: {baseline} -> {final}")
    if sequential_fds > baseline_fds + 2 or final_fds > baseline_fds + 2:
        raise AssertionError(
            f"router FD count did not return to baseline: baseline={baseline_fds}, "
            f"sequential={sequential_fds}, final={final_fds}"
        )

    print(
        json.dumps(
            {
                "router_pid": args.pid,
                "baseline": baseline,
                "after_half_close": after_half_close,
                "after_empty_response": after_empty_response,
                "after_full_close": after_full_close,
                "after_sequential": after_sequential,
                "final": final,
                "sequential_lifecycles": args.sequential,
                "wave_results": wave_results,
                "fd_counts": {
                    "baseline": baseline_fds,
                    "max_sampled": max_sampled_fds,
                    "after_sequential": sequential_fds,
                    "final": final_fds,
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
