#!/usr/bin/env python3
"""Send manual prompts through XDP keyword routing and report rough timing."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import http.client
import http.server
import json
import os
import queue
import select
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://10.10.0.1:18081/v1/chat/completions"
DEFAULT_MOCK_HOST = "0.0.0.0"
DEFAULT_MOCK_PORT = 18081
DEFAULT_XDP_IFNAME = "veth0"
DEFAULT_XDP_NETNS = "ns1"

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
    route: str | None = None
    matched_keywords: dict[str, bool] | None = None
    xdp_elapsed_ns: int | None = None
    error: str | None = None


class MockBackendHandler(http.server.BaseHTTPRequestHandler):
    server_version = "XdpKeywordSmokeMock/0.1"

    def do_POST(self) -> None:
        content_length = int(self.headers.get("content-length", "0"))
        self.rfile.read(content_length)
        payload = {
            "id": "xdp-keyword-smoke",
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
    c_binary = ROOT / "tests" / "mock_backend"
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
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()


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
            "model": "benchmark-model",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        separators=(",", ":"),
    ).encode()


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
        return RequestResult(prompt=prompt, status=response.status, elapsed_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return RequestResult(prompt=prompt, status=0, elapsed_ms=elapsed_ms, error=str(exc))
    finally:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass


def run_client_worker(url: str, timeout_s: float) -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        payload = json.loads(line)
        result = send_prompt(url, payload["prompt"], timeout_s)
        print(json.dumps(dataclasses.asdict(result), separators=(",", ":")), flush=True)
    return 0


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


def process_cpu_percent(pid: int) -> float | None:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "%cpu="],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except Exception:
        return None
    value = completed.stdout.strip()
    return float(value) if value else None


class ProcessCpuSampler:
    def __init__(self, pid: int, interval_s: float) -> None:
        self.pid = pid
        self.interval_s = interval_s
        self.samples: list[float] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "ProcessCpuSampler":
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval_s + 2)

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = process_cpu_percent(self.pid)
            if sample is not None:
                self.samples.append(sample)
            self._stop.wait(self.interval_s)

    def average(self) -> float | None:
        return sum(self.samples) / len(self.samples) if self.samples else None

    def maximum(self) -> float | None:
        return max(self.samples) if self.samples else None


def run_checked(command: list[str], **kwargs: Any) -> None:
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def add_input_allow_rule(ifname: str, port: int) -> None:
    run_checked(
        [
            "iptables",
            "-I",
            "INPUT",
            "1",
            "-i",
            ifname,
            "-p",
            "tcp",
            "--dport",
            str(port),
            "-j",
            "ACCEPT",
        ]
    )


def remove_input_allow_rule(ifname: str, port: int) -> None:
    subprocess.run(
        [
            "iptables",
            "-D",
            "INPUT",
            "-i",
            ifname,
            "-p",
            "tcp",
            "--dport",
            str(port),
            "-j",
            "ACCEPT",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def read_router_output(router: subprocess.Popen[str], output: queue.Queue[str]) -> None:
    if not router.stdout:
        return
    for line in router.stdout:
        output.put(line.rstrip())


def wait_for_router(router: subprocess.Popen[str], output: queue.Queue[str], timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if router.poll() is not None:
            return False
        try:
            line = output.get(timeout=0.2)
        except queue.Empty:
            continue
        if "XDP attached" in line:
            return True
    return False


def drain_route_events(output: queue.Queue[str], wanted: int, timeout_s: float) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    deadline = time.time() + timeout_s
    while len(events) < wanted and time.time() < deadline:
        try:
            line = output.get(timeout=max(0.1, deadline - time.time()))
        except queue.Empty:
            break
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "route":
            events.append(event)
    return events


def ensure_xdp_prereqs(ifname: str, netns: str) -> None:
    if os.geteuid() != 0:
        raise SystemExit("XDP smoke probe requires root. Try: sudo python3 tests/probe_xdp_keyword_smoke.py")
    if not shutil.which("ip"):
        raise SystemExit("iproute2 is required for the XDP smoke probe")
    for command in (["ip", "link", "show", "dev", ifname], ["ip", "netns", "exec", netns, "true"]):
        try:
            run_checked(command)
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                f"missing XDP prerequisite: {' '.join(command)}. "
                "Run `sudo make setup` or pass --setup."
            ) from exc


def run_netns_client(
    netns: str,
    url: str,
    prompts: list[str],
    rounds: int,
    timeout_s: float,
) -> list[RequestResult]:
    worker = subprocess.Popen(
        [
            "ip",
            "netns",
            "exec",
            netns,
            sys.executable,
            "-u",
            str(Path(__file__).resolve()),
            "--client-worker",
            normalize_chat_url(url),
            "--timeout-s",
            str(timeout_s),
        ],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        assert worker.stdin is not None
        for _ in range(rounds):
            for prompt in prompts:
                worker.stdin.write(json.dumps({"prompt": prompt}, separators=(",", ":")) + "\n")
        worker.stdin.close()

        assert worker.stdout is not None
        results: list[RequestResult] = []
        for line in worker.stdout:
            results.append(RequestResult(**json.loads(line)))

        stderr = worker.stderr.read() if worker.stderr else ""
        if worker.wait(timeout=5) != 0:
            raise RuntimeError(f"netns client worker failed: {stderr.strip()}")
        return results
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)


def summarize(results: list[RequestResult], cpu: ProcessCpuSampler) -> dict[str, Any]:
    latencies = [result.elapsed_ms for result in results if result.status]
    xdp_latencies = [
        result.xdp_elapsed_ns
        for result in results
        if result.xdp_elapsed_ns is not None
    ]
    return {
        "requests": len(results),
        "successes": sum(1 for result in results if 200 <= result.status < 300),
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "avg_xdp_elapsed_ns": sum(xdp_latencies) / len(xdp_latencies) if xdp_latencies else None,
        "max_xdp_elapsed_ns": max(xdp_latencies) if xdp_latencies else None,
        "avg_router_process_cpu_percent": cpu.average(),
        "max_router_process_cpu_percent": cpu.maximum(),
        "router_process_cpu_samples": len(cpu.samples),
        "results": [dataclasses.asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--mock-host", default=DEFAULT_MOCK_HOST)
    parser.add_argument("--mock-port", type=int, default=DEFAULT_MOCK_PORT)
    parser.add_argument("--xdp-ifname", default=DEFAULT_XDP_IFNAME)
    parser.add_argument("--xdp-netns", default=DEFAULT_XDP_NETNS)
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--event-timeout-s", type=float, default=5.0)
    parser.add_argument("--cpu-interval-s", type=float, default=0.25)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--no-mock-backend", action="store_true")
    parser.add_argument("--no-firewall", action="store_true")
    parser.add_argument("--client-worker")
    args = parser.parse_args()

    if args.client_worker:
        return run_client_worker(args.client_worker, args.timeout_s)

    if args.setup:
        run_checked(["make", "setup"])
    ensure_xdp_prereqs(args.xdp_ifname, args.xdp_netns)
    if not args.no_build:
        run_checked(["make", "dev"])

    subprocess.run(
        ["ip", "link", "set", "dev", args.xdp_ifname, "xdp", "off"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    router: subprocess.Popen[str] | None = None
    firewall_rule_added = False
    output: queue.Queue[str] = queue.Queue()
    backend_ctx = (
        contextlib.nullcontext()
        if args.no_mock_backend
        else run_mock_backend(args.mock_host, args.mock_port)
    )

    try:
        if not args.no_firewall:
            add_input_allow_rule(args.xdp_ifname, args.mock_port)
            firewall_rule_added = True

        router = subprocess.Popen(
            [str(ROOT / "xdp_router")],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=read_router_output, args=(router, output), daemon=True).start()
        if not wait_for_router(router, output, 10):
            raise SystemExit("xdp_router did not attach")

        host_cpu_start = read_cpu_totals()
        with backend_ctx:
            with ProcessCpuSampler(router.pid, args.cpu_interval_s) as cpu:
                results = run_netns_client(
                    args.xdp_netns,
                    args.url,
                    list(PROMPTS),
                    args.rounds,
                    args.timeout_s,
                )
                events = drain_route_events(output, len(results), args.event_timeout_s)
        host_cpu_end = read_cpu_totals()

        for result, event in zip(results, events):
            result.route = event.get("route_name")
            result.matched_keywords = event.get("matched_keywords")
            result.xdp_elapsed_ns = event.get("xdp_elapsed_ns")

        summary = summarize(results, cpu)
        summary["route_events"] = len(events)
        summary["host_cpu_percent"] = cpu_percent(host_cpu_start, host_cpu_end)
        print(json.dumps(summary, indent=2))
        return 0
    finally:
        if router:
            router.terminate()
            try:
                router.wait(timeout=5)
            except subprocess.TimeoutExpired:
                router.kill()
                router.wait(timeout=5)
            if router.stdout:
                router.stdout.close()
        if firewall_rule_added:
            remove_input_allow_rule(args.xdp_ifname, args.mock_port)
        subprocess.run(
            ["ip", "link", "set", "dev", args.xdp_ifname, "xdp", "off"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    raise SystemExit(main())
