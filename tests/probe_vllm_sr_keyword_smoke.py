#!/usr/bin/env python3
"""Send manual prompts through vLLM-SR keyword routing and report rough timing."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import http.client
import http.server
import json
import queue
import socket
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:8899/v1/chat/completions"
DEFAULT_BACKEND_HOST = "0.0.0.0"
DEFAULT_BACKEND_PORT = 18391
ROUTE_HEADERS = (
    "x-vllm-sr-route",
    "x-vsr-selected-decision",
    "x-vsr-selected-model",
    "x-selected-model",
)
CPU_CONTAINERS = ("vllm-sr-router-container", "vllm-sr-envoy-container")


PROMPTS = (
    "Please debug this Python function and explain the code path.",
    "Solve this matrix equation and calculate the probability.",
    "Write a short friendly paragraph about planning a weekend lunch.",
    "Refactor this algorithm to make the function easier to test.",
    "What is the derivative of x squared?",
)


@dataclasses.dataclass
class RequestResult:
    prompt: str
    status: int
    elapsed_ms: float
    route: str | None
    error: str | None = None


class MockBackendHandler(http.server.BaseHTTPRequestHandler):
    server_version = "KeywordSmokeMock/0.1"

    def do_POST(self) -> None:
        content_length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(content_length)
        self.server.requests.put(body)  # type: ignore[attr-defined]
        payload = {
            "id": "keyword-smoke",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }
        response = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


@contextlib.contextmanager
def run_mock_backend(host: str, port: int):
    c_binary = ROOT / "benchmarks" / "mock_backend"
    if c_binary.exists() and os.access(c_binary, os.X_OK):
        proc = subprocess.Popen(
            [str(c_binary), str(port)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.1)
        try:
            yield proc
        finally:
            proc.kill()
            proc.wait(timeout=2)
    else:
        server = ThreadingHTTPServer((host, port), MockBackendHandler)
        server.requests = queue.Queue()  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()


def socket_open(host: str, port: int, timeout_s: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def normalize_chat_url(value: str) -> str:
    url = value.rstrip("/")
    if url.endswith("/v1/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/v1/chat/completions"


def openai_body(prompt: str) -> bytes:
    return json.dumps(
        {
            "model": "MoM",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        separators=(",", ":"),
    ).encode()


def canonical_route(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().replace("_", "-")
    for suffix in ("-route", "-model"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    if "coding" in normalized or "code" in normalized:
        return "coding"
    if "math" in normalized:
        return "math"
    if "other" in normalized or "general" in normalized or "default" in normalized:
        return "others"
    return normalized or None


def route_from_headers(headers: dict[str, str]) -> str | None:
    for header in ROUTE_HEADERS:
        route = canonical_route(headers.get(header))
        if route:
            return route
    return None


def send_prompt(url: str, prompt: str, timeout_s: float) -> RequestResult:
    parsed = urllib.parse.urlparse(url)
    start = time.perf_counter_ns()
    try:
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout_s)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        conn.request(
            "POST",
            path,
            body=openai_body(prompt),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        response.read()
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        headers = {key.lower(): value for key, value in response.getheaders()}
        return RequestResult(
            prompt=prompt,
            status=response.status,
            elapsed_ms=elapsed_ms,
            route=route_from_headers(headers),
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return RequestResult(prompt=prompt, status=0, elapsed_ms=elapsed_ms, route=None, error=str(exc))
    finally:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass


def parse_cpu_percent(value: str) -> float:
    return float(value.strip().rstrip("%"))


def docker_cpu_snapshot(containers: tuple[str, ...]) -> float | None:
    command = [
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "{{.CPUPerc}}",
        *containers,
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        return None

    total = 0.0
    saw_value = False
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        total += parse_cpu_percent(line)
        saw_value = True
    return total if saw_value else None


def read_cpu_totals() -> tuple[int, int] | None:
    try:
        with open("/proc/stat") as file:
            fields = file.readline().split()
    except OSError:
        return None

    if not fields or fields[0] != "cpu":
        return None
    values = [int(value) for value in fields[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return total, idle


def cpu_percent(start: tuple[int, int] | None, end: tuple[int, int] | None) -> float | None:
    if start is None or end is None:
        return None
    total_delta = end[0] - start[0]
    idle_delta = end[1] - start[1]
    if total_delta <= 0:
        return None
    return 100.0 * (total_delta - idle_delta) / total_delta


class CpuSampler:
    def __init__(self, containers: tuple[str, ...], interval_s: float) -> None:
        self.containers = containers
        self.interval_s = interval_s
        self.samples: list[float] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "CpuSampler":
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval_s + 5)

    def _run(self) -> None:
        while not self._stop.is_set():
            value = docker_cpu_snapshot(self.containers)
            if value is not None:
                self.samples.append(value)
            self._stop.wait(self.interval_s)

    def average(self) -> float | None:
        if not self.samples:
            return None
        return sum(self.samples) / len(self.samples)

    def maximum(self) -> float | None:
        if not self.samples:
            return None
        return max(self.samples)


def summarize(results: list[RequestResult], cpu: CpuSampler) -> dict[str, Any]:
    latencies = [result.elapsed_ms for result in results if result.status]
    return {
        "requests": len(results),
        "successes": sum(1 for result in results if 200 <= result.status < 300),
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "avg_container_cpu_percent": cpu.average(),
        "max_container_cpu_percent": cpu.maximum(),
        "container_cpu_samples": len(cpu.samples),
        "results": [dataclasses.asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--backend-host", default=DEFAULT_BACKEND_HOST)
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--timeout-s", type=float, default=20.0)
    parser.add_argument("--cpu-interval-s", type=float, default=0.25)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--no-mock-backend", action="store_true")
    args = parser.parse_args()

    url = normalize_chat_url(args.url)
    if not socket_open("127.0.0.1", urllib.parse.urlparse(url).port or 80):
        raise SystemExit(f"vLLM-SR endpoint is not reachable: {url}")

    backend_ctx = (
        contextlib.nullcontext()
        if args.no_mock_backend
        else run_mock_backend(args.backend_host, args.backend_port)
    )
    with backend_ctx:
        host_cpu_start = read_cpu_totals()
        with CpuSampler(CPU_CONTAINERS, args.cpu_interval_s) as cpu:
            results = [
                send_prompt(url, prompt, args.timeout_s)
                for _ in range(args.rounds)
                for prompt in PROMPTS
            ]
        host_cpu_end = read_cpu_totals()

    summary = summarize(results, cpu)
    summary["host_cpu_percent"] = cpu_percent(host_cpu_start, host_cpu_end)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
