#!/usr/bin/env python3
"""Compare XDP and vLLM-SR on the shared keyword routing policy."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import http.client
import http.server
import json
import os
import platform
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_keyword_header import load_policy, validate_policy  # noqa: E402


DEFAULT_CONFIG = ROOT / "config" / "vllm_sr_keyword_config.yaml"
DEFAULT_REPORT_DIR = ROOT / "reports" / "keyword-routing"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "xdp-keyword-routing"
DEFAULT_XDP_URL = "http://10.10.0.1:18081/v1/chat/completions"
DEFAULT_VLLM_SR_URL = "http://127.0.0.1:8899/v1/chat/completions"
ROUTES = ("coding", "math", "others")
ROUTE_HEADERS = (
    "x-vllm-sr-route",
    "x-vsr-selected-decision",
    "x-vsr-selected-model",
    "x-selected-model",
)


DATASETS = {
    "supralabs": {
        "dataset": "SupraLabs/Prompt-Routing-Dataset",
        "config": "default",
        "split": "train",
    },
    "empero-tasklist": {
        "dataset": "empero-ai/tasklist-qwen3.5-9B-7500x-unfiltered",
        "config": "default",
        "split": "train",
    },
    "speed-bench": {
        "dataset": "nvidia/SPEED-Bench",
        "config": "qualitative",
        "split": "test",
    },
    "synthetic-pld": {
        "dataset": "mayankthakur/synthetic-pld-benchmark",
        "config": "default",
        "split": "train",
    },
}


@dataclasses.dataclass(frozen=True)
class Case:
    prompt: str
    expected_route: str
    matched_keyword: str | None
    source_index: int


@dataclasses.dataclass
class Result:
    prompt: str
    expected_route: str
    status: int
    elapsed_ms: float
    route: str | None
    matched_keyword: str | None
    xdp_elapsed_ns: int | None = None
    error: str | None = None


class MockBackend(http.server.BaseHTTPRequestHandler):
    server_version = "KeywordBenchmarkMock/0.1"

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        body = b'{"id":"keyword-benchmark","choices":[{"message":{"content":"ok"}}]}\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 4096


@contextlib.contextmanager
def mock_backend(port: int):
    server = ThreadingHTTPServer(("0.0.0.0", port), MockBackend)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()


def chat_url(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith("/v1/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/v1/chat/completions"


def chat_body(prompt: str) -> bytes:
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


def send_case(url: str, case: Case, timeout_s: float) -> Result:
    parsed = urllib.parse.urlparse(chat_url(url))
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    start = time.perf_counter_ns()
    try:
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout_s)
        conn.request(
            "POST",
            path,
            body=chat_body(case.prompt),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        response.read()
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        headers = {key.lower(): value for key, value in response.getheaders()}
        return Result(
            case.prompt,
            case.expected_route,
            response.status,
            elapsed_ms,
            route_from_headers(headers),
            case.matched_keyword,
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return Result(
            case.prompt,
            case.expected_route,
            0,
            elapsed_ms,
            None,
            case.matched_keyword,
            error=str(exc),
        )
    finally:
        with contextlib.suppress(Exception):
            conn.close()  # type: ignore[name-defined]


def run_client_worker(url: str, timeout_s: float) -> int:
    for line in sys.stdin:
        item = json.loads(line)
        case = Case(
            item["prompt"],
            item["expected_route"],
            item.get("matched_keyword"),
            item.get("source_index", 0),
        )
        print(json.dumps(dataclasses.asdict(send_case(url, case, timeout_s))), flush=True)
    return 0


def prompt_from_row(row: dict[str, Any]) -> str | None:
    turns = row.get("turns")
    if isinstance(turns, list):
        parts = [turn.strip() for turn in turns if isinstance(turn, str) and turn.strip()]
        if parts:
            return "\n\n".join(parts)
    for key in ("prompt", "instruction", "question", "input", "text"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def load_rows(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = DATASETS[args.dataset]
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = args.cache_dir / (
        f"{spec['dataset'].replace('/', '__')}-{spec['config']}-{spec['split']}.jsonl"
    )

    cached: list[dict[str, Any]] = []
    if cache_path.exists():
        with cache_path.open() as file:
            cached = [json.loads(line) for line in file if line.strip()]
        if len(cached) >= args.scan_limit:
            return cached[: args.scan_limit], dataset_meta(args, spec, "cache", args.scan_limit)

    rows: list[dict[str, Any]] = []
    try:
        while len(rows) < args.scan_limit:
            query = urllib.parse.urlencode(
                {
                    "dataset": spec["dataset"],
                    "config": spec["config"],
                    "split": spec["split"],
                    "offset": len(rows),
                    "length": min(100, args.scan_limit - len(rows)),
                }
            )
            with urllib.request.urlopen(
                f"https://datasets-server.huggingface.co/rows?{query}",
                timeout=60,
            ) as response:
                data = json.load(response)
            page = [item["row"] for item in data.get("rows", [])]
            if not page:
                break
            rows.extend(page)
    except Exception:
        if cached:
            return cached, dataset_meta(args, spec, "cache-partial", len(cached))
        raise

    with cache_path.open("w") as file:
        for row in rows:
            file.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    return rows, dataset_meta(args, spec, "dataset-server", len(rows))


def dataset_meta(
    args: argparse.Namespace,
    spec: dict[str, str],
    loader: str,
    scanned_rows: int,
) -> dict[str, Any]:
    return {
        "name": args.dataset,
        "source": spec["dataset"],
        "config": spec["config"],
        "split": spec["split"],
        "loader": loader,
        "scanned_rows": scanned_rows,
        "requested_per_route": args.per_route,
    }


def expected_route(
    prompt: str,
    routes: list[dict[str, object]],
    case_sensitive: bool,
) -> tuple[str, str | None]:
    text = prompt if case_sensitive else prompt.lower()
    for route in routes:
        for keyword in route["keywords"]:  # type: ignore[index]
            token = str(keyword) if case_sensitive else str(keyword).lower()
            if token in text:
                return str(route["name"]), token
    return "others", None


def select_cases(
    rows: list[dict[str, Any]],
    routes: list[dict[str, object]],
    case_sensitive: bool,
    per_route: int,
) -> tuple[list[Case], dict[str, int]]:
    buckets: dict[str, list[Case]] = {route: [] for route in ROUTES}
    counts = {"missing_prompt": 0, "duplicate_prompt": 0, "embedded_quote": 0}
    seen: set[str] = set()

    for index, row in enumerate(rows):
        prompt = prompt_from_row(row)
        if not prompt:
            counts["missing_prompt"] += 1
            continue
        if '"' in prompt:
            counts["embedded_quote"] += 1
            continue
        key = " ".join(prompt.split()).lower()
        if key in seen:
            counts["duplicate_prompt"] += 1
            continue
        seen.add(key)

        route, keyword = expected_route(prompt, routes, case_sensitive)
        if len(buckets[route]) < per_route:
            buckets[route].append(Case(prompt, route, keyword, index))
        if all(len(buckets[route]) >= per_route for route in ROUTES):
            break

    cases = [case for route in ROUTES for case in buckets[route]]
    counts.update({route: len(buckets[route]) for route in ROUTES})
    if any(counts[route] < per_route for route in ROUTES):
        missing = ", ".join(f"{route}={counts[route]}" for route in ROUTES)
        raise SystemExit(f"not enough dataset prompts for requested sample: {missing}")
    return cases, counts


def load_cases(args: argparse.Namespace) -> tuple[list[Case], dict[str, Any], dict[str, Any]]:
    policy = load_policy(args.config)
    case_sensitive, routes = validate_policy(policy)
    rows, meta = load_rows(args)
    cases, selected_counts = select_cases(rows, routes, case_sensitive, args.per_route)
    meta["selected_counts"] = selected_counts
    policy_meta = {
        "case_sensitive": case_sensitive,
        "keyword_count": sum(len(route["keywords"]) for route in routes),  # type: ignore[arg-type]
        "routes": routes,
    }
    return cases, meta, policy_meta


def read_cpu() -> tuple[int, int] | None:
    try:
        fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    except OSError:
        return None
    values = [int(value) for value in fields]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_delta(start: tuple[int, int] | None, end: tuple[int, int] | None) -> float | None:
    if not start or not end:
        return None
    total = end[0] - start[0]
    idle = end[1] - start[1]
    return None if total <= 0 else 100.0 * (total - idle) / total


def sampled_cpu(pid: int | None = None, containers: tuple[str, ...] = ()) -> float | None:
    try:
        if containers:
            completed = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}", *containers],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
            values = [float(line.strip().rstrip("%")) for line in completed.stdout.splitlines()]
            return sum(values) if values else None
        if pid is not None:
            completed = subprocess.run(
                ["ps", "-p", str(pid), "-o", "%cpu="],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            )
            value = completed.stdout.strip()
            return float(value) if value else None
    except Exception:
        return None
    return None


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[int(round((pct / 100.0) * (len(ordered) - 1)))]


def summarize(mode: str, results: list[Result], wall_s: float, host_cpu: float | None, cpu: float | None) -> dict[str, Any]:
    latencies = [result.elapsed_ms for result in results if result.status and not result.error]
    correct = sum(1 for result in results if result.route == result.expected_route)
    mismatches = [
        {
            "expected": result.expected_route,
            "actual": result.route,
            "matched_keyword": result.matched_keyword,
            "prompt": result.prompt[:160],
        }
        for result in results
        if result.route != result.expected_route
    ]
    counts = {route: 0 for route in ROUTES}
    counts["unknown"] = 0
    for result in results:
        counts[result.route if result.route in ROUTES else "unknown"] += 1

    xdp_ns = [result.xdp_elapsed_ns for result in results if result.xdp_elapsed_ns is not None]
    return {
        "mode": mode,
        "status": "ok",
        "requests": len(results),
        "successes": sum(1 for result in results if 200 <= result.status < 300),
        "errors": sum(1 for result in results if result.error or result.status >= 400 or result.status == 0),
        "route_agreement": correct / len(results) if results else None,
        "correct_routes": correct,
        "route_counts": counts,
        "latency_ms": {
            "avg": sum(latencies) / len(latencies) if latencies else None,
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
            "max": max(latencies) if latencies else None,
        },
        "xdp_elapsed_ns": {
            "avg": sum(xdp_ns) / len(xdp_ns) if xdp_ns else None,
            "max": max(xdp_ns) if xdp_ns else None,
        },
        "requests_per_second": len(results) / wall_s if wall_s > 0 else 0.0,
        "host_cpu_percent": host_cpu,
        "sampled_cpu_percent": cpu,
        "mismatches": mismatches[:10],
    }


def socket_open(url: str) -> bool:
    parsed = urllib.parse.urlparse(chat_url(url))
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=0.5):
            return True
    except OSError:
        return False


def run_vllm(args: argparse.Namespace, cases: list[Case]) -> dict[str, Any]:
    if not socket_open(args.vllm_sr_url):
        return {"mode": "vllm-sr", "status": "skipped", "reason": "vLLM-SR endpoint is not reachable"}
    cpu_start = read_cpu()
    start = time.perf_counter()
    results = [send_case(args.vllm_sr_url, case, args.timeout_s) for case in cases]
    wall_s = time.perf_counter() - start
    return summarize(
        "vllm-sr",
        results,
        wall_s,
        cpu_delta(cpu_start, read_cpu()),
        sampled_cpu(containers=("vllm-sr-router-container", "vllm-sr-envoy-container")),
    )


def checked(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_xdp(args: argparse.Namespace) -> str | None:
    if os.geteuid() != 0:
        return "XDP mode requires root"
    if not shutil.which("ip"):
        return "iproute2 is required"
    if args.setup:
        checked(["make", "setup"])
    for command in (
        ["ip", "link", "show", "dev", args.xdp_ifname],
        ["ip", "netns", "exec", args.xdp_netns, "true"],
    ):
        try:
            checked(command)
        except subprocess.CalledProcessError:
            return f"missing prerequisite: {' '.join(command)}"
    if not args.no_build:
        checked(["make", "dev"])
    subprocess.run(["ip", "link", "set", "dev", args.xdp_ifname, "xdp", "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None


def iptables_allow(ifname: str, port: int) -> None:
    checked(["iptables", "-I", "INPUT", "1", "-i", ifname, "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"])


def iptables_remove(ifname: str, port: int) -> None:
    subprocess.run(
        ["iptables", "-D", "INPUT", "-i", ifname, "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def read_router(router: subprocess.Popen[str], out: queue.Queue[str]) -> None:
    if router.stdout:
        for line in router.stdout:
            out.put(line.rstrip())


def wait_for_attach(router: subprocess.Popen[str], out: queue.Queue[str]) -> bool:
    deadline = time.time() + 10
    while time.time() < deadline:
        if router.poll() is not None:
            return False
        try:
            if "XDP attached" in out.get(timeout=0.2):
                return True
        except queue.Empty:
            pass
    return False


def route_events(out: queue.Queue[str], wanted: int, timeout_s: float) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    deadline = time.time() + timeout_s
    while len(events) < wanted and time.time() < deadline:
        try:
            line = out.get(timeout=max(0.1, deadline - time.time()))
        except queue.Empty:
            break
        if not line.startswith("{"):
            continue
        with contextlib.suppress(json.JSONDecodeError):
            event = json.loads(line)
            if event.get("event") == "route":
                events.append(event)
    return events


def netns_requests(args: argparse.Namespace, cases: list[Case]) -> list[Result]:
    worker = subprocess.Popen(
        [
            "ip",
            "netns",
            "exec",
            args.xdp_netns,
            sys.executable,
            "-u",
            str(Path(__file__).resolve()),
            "--client-worker",
            chat_url(args.xdp_url),
            "--timeout-s",
            str(args.timeout_s),
        ],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert worker.stdin and worker.stdout
        for case in cases:
            worker.stdin.write(json.dumps(dataclasses.asdict(case), separators=(",", ":")) + "\n")
        worker.stdin.close()
        results = [Result(**json.loads(line)) for line in worker.stdout if line.strip()]
        stderr = worker.stderr.read() if worker.stderr else ""
        if worker.wait(timeout=5) != 0:
            raise RuntimeError(stderr.strip())
        return results
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)


def run_direct_netns(args: argparse.Namespace, cases: list[Case]) -> dict[str, Any]:
    reason = ensure_xdp(args)
    if reason:
        return {"mode": "direct-netns", "status": "skipped", "reason": reason}

    firewall = False
    try:
        if not args.no_firewall:
            iptables_allow(args.xdp_ifname, args.xdp_backend_port)
            firewall = True

        cpu_start = read_cpu()
        start = time.perf_counter()
        results = netns_requests(args, cases)
        wall_s = time.perf_counter() - start
        host_cpu = cpu_delta(cpu_start, read_cpu())

        summary = summarize("direct-netns", results, wall_s, host_cpu, None)
        return summary
    finally:
        if firewall:
            iptables_remove(args.xdp_ifname, args.xdp_backend_port)
        subprocess.run(["ip", "link", "set", "dev", args.xdp_ifname, "xdp", "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_xdp(args: argparse.Namespace, cases: list[Case]) -> dict[str, Any]:
    reason = ensure_xdp(args)
    if reason:
        return {"mode": "xdp", "status": "skipped", "reason": reason}

    router: subprocess.Popen[str] | None = None
    firewall = False
    out: queue.Queue[str] = queue.Queue()
    try:
        if not args.no_firewall:
            iptables_allow(args.xdp_ifname, args.xdp_backend_port)
            firewall = True
        router = subprocess.Popen([str(ROOT / "xdp_router")], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=read_router, args=(router, out), daemon=True).start()
        if not wait_for_attach(router, out):
            return {"mode": "xdp", "status": "skipped", "reason": "xdp_router did not attach"}

        cpu_start = read_cpu()
        start = time.perf_counter()
        results = netns_requests(args, cases)
        wall_s = time.perf_counter() - start
        host_cpu = cpu_delta(cpu_start, read_cpu())
        events = route_events(out, len(results), args.event_timeout_s)
        for result, event in zip(results, events):
            result.route = canonical_route(event.get("route_name"))
            result.xdp_elapsed_ns = event.get("xdp_elapsed_ns")

        summary = summarize("xdp", results, wall_s, host_cpu, sampled_cpu(pid=router.pid))
        summary["route_events"] = len(events)
        summary["missing_route_events"] = max(0, len(results) - len(events))
        return summary
    finally:
        if router:
            router.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                router.wait(timeout=5)
            if router.poll() is None:
                router.kill()
                router.wait(timeout=5)
        if firewall:
            iptables_remove(args.xdp_ifname, args.xdp_backend_port)
        subprocess.run(["ip", "link", "set", "dev", args.xdp_ifname, "xdp", "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def comparison(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = {item["mode"]: item for item in results if item.get("status") == "ok"}
    if "xdp" not in ok or "vllm-sr" not in ok:
        return {"status": "incomplete", "reason": "both modes must complete"}
    xdp, vllm = ok["xdp"], ok["vllm-sr"]
    xdp_avg = xdp["latency_ms"]["avg"]
    vllm_avg = vllm["latency_ms"]["avg"]
    xdp_p99 = xdp["latency_ms"]["p99"]
    vllm_p99 = vllm["latency_ms"]["p99"]
    xdp_rps = xdp["requests_per_second"]
    vllm_rps = vllm["requests_per_second"]

    avg_speedup = (vllm_avg / xdp_avg) if (vllm_avg and xdp_avg) else None
    p99_speedup = (vllm_p99 / xdp_p99) if (vllm_p99 and xdp_p99) else None
    rps_speedup = (xdp_rps / vllm_rps) if (xdp_rps and vllm_rps) else None

    return {
        "status": "ok",
        "route_agreement_delta": (xdp["route_agreement"] or 0) - (vllm["route_agreement"] or 0),
        "avg_latency_delta_ms": (xdp_avg or 0) - (vllm_avg or 0),
        "p99_latency_delta_ms": (xdp_p99 or 0) - (vllm_p99 or 0),
        "avg_speedup": avg_speedup,
        "p99_speedup": p99_speedup,
        "rps_speedup": rps_speedup,
    }


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def write_reports(report: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "keyword_routing_benchmark.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    dataset = report["dataset"]
    selected = dataset["selected_counts"]
    control_results = [r for r in report["results"] if r.get("mode") in {"direct-netns", "direct"}]
    test_results = [r for r in report["results"] if r.get("mode") not in {"direct-netns", "direct"}]

    lines = [
        "# Keyword Routing Benchmark",
        "",
        f"- Dataset: `{dataset['source']}`",
        f"- Total rows: {dataset['scanned_rows']}",
        f"- Selected prompts: coding={selected['coding']}, math={selected['math']}, others={selected['others']}",
        f"- Filtered rows: embedded_quote={selected['embedded_quote']}, duplicate_prompt={selected['duplicate_prompt']}, missing_prompt={selected['missing_prompt']}",
        f"- Policy: case_sensitive={report['policy']['case_sensitive']}; keywords={report['policy']['keyword_count']}",
        "",
    ]

    if control_results:
        lines += [
            "## Control Result",
            "",
            "| Mode | Requests | avg ms | p99 ms | RPS | Host CPU % | Sampled CPU % |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for result in control_results:
            if result.get("status") != "ok":
                lines.append(f"| {result['mode']} | 0 | n/a | n/a | n/a | n/a | n/a |")
                continue
            latency = result["latency_ms"]
            lines.append(
                f"| {result['mode']} | {result['requests']} | "
                f"{fmt(latency['avg'])} | {fmt(latency['p99'])} | "
                f"{fmt(result['requests_per_second'])} | {fmt(result['host_cpu_percent'])} | {fmt(result['sampled_cpu_percent'])} |"
            )
        lines.append("")

    lines += [
        "## Results",
        "",
        "| Mode | Requests | Route agreement | avg ms | p99 ms | RPS | Host CPU % | Sampled CPU % |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in test_results:
        if result.get("status") != "ok":
            lines.append(f"| {result['mode']} | 0 | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        latency = result["latency_ms"]
        lines.append(
            f"| {result['mode']} | {result['requests']} | {fmt(result['route_agreement'], 4)} | "
            f"{fmt(latency['avg'])} | {fmt(latency['p99'])} | "
            f"{fmt(result['requests_per_second'])} | {fmt(result['host_cpu_percent'])} | {fmt(result['sampled_cpu_percent'])} |"
        )

    lines += ["", "## Route Counts", "", "| Mode | coding | math | others |", "| --- | ---: | ---: | ---: |"]
    for result in test_results:
        counts = result.get("route_counts") or {}
        lines.append(f"| {result['mode']} | {counts.get('coding', 0)} | {counts.get('math', 0)} | {counts.get('others', 0)} |")

    comp = report["comparison"]
    lines += ["", "## Comparison", ""]
    if comp["status"] == "ok":
        if comp.get("avg_speedup") is not None or comp.get("p99_speedup") is not None or comp.get("rps_speedup") is not None:
            lines += [
                "| Metric | avg speedup | p99 speedup | RPS speedup |",
                "| --- | ---: | ---: | ---: |",
                f"| XDP vs vLLM-SR | {fmt(comp.get('avg_speedup'), 2)}x | {fmt(comp.get('p99_speedup'), 2)}x | {fmt(comp.get('rps_speedup'), 2)}x |",
                "",
            ]
        lines += [
            f"- Route agreement delta, XDP minus vLLM-SR: {fmt(comp['route_agreement_delta'], 4)}",
            f"- Average latency delta, XDP minus vLLM-SR: {fmt(comp['avg_latency_delta_ms'])} ms",
            f"- p99 latency delta, XDP minus vLLM-SR: {fmt(comp['p99_latency_delta_ms'])} ms",
        ]
    else:
        lines.append(f"- Comparison incomplete: {comp.get('reason', 'unknown')}")

    mismatches = [
        f"- {result['mode']}: expected `{item['expected']}`, got `{item['actual']}`; keyword `{item['matched_keyword']}`; prompt: {item['prompt']!r}"
        for result in test_results
        for item in result.get("mismatches", [])
    ]
    if mismatches:
        lines += ["", "## First Mismatches", "", *mismatches[:10]]

    lines += [
        "",
        "Note: Sampled CPU % for XDP measures the userspace logger process (xdp_router) handling XDP_DEBUG ring-buffer polling. In production without debug logging, the CPU usage is negligible.",
    ]

    (report_dir / "keyword_routing_benchmark.md").write_text("\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-worker")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="supralabs")
    parser.add_argument("--scan-limit", type=int, default=2000)
    parser.add_argument("--per-route", type=int, default=50)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--modes", default="direct-netns,xdp,vllm-sr")
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--event-timeout-s", type=float, default=10.0)
    parser.add_argument("--xdp-url", default=DEFAULT_XDP_URL)
    parser.add_argument("--xdp-ifname", default="veth0")
    parser.add_argument("--xdp-netns", default="ns1")
    parser.add_argument("--xdp-backend-port", type=int, default=18081)
    parser.add_argument("--vllm-sr-url", default=DEFAULT_VLLM_SR_URL)
    parser.add_argument("--vllm-backend-port", type=int, default=18391)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--no-firewall", action="store_true")
    parser.add_argument("--no-mock-backends", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.client_worker:
        return run_client_worker(args.client_worker, args.timeout_s)

    cases, dataset, policy = load_cases(args)
    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    results: list[dict[str, Any]] = []

    with contextlib.ExitStack() as stack:
        if not args.no_mock_backends:
            if "direct-netns" in modes or "xdp" in modes:
                stack.enter_context(mock_backend(args.xdp_backend_port))
            if "vllm-sr" in modes:
                stack.enter_context(mock_backend(args.vllm_backend_port))
        for mode in modes:
            if mode == "direct-netns":
                results.append(run_direct_netns(args, cases))
            elif mode == "xdp":
                results.append(run_xdp(args, cases))
            elif mode == "vllm-sr":
                results.append(run_vllm(args, cases))
            else:
                results.append({"mode": mode, "status": "skipped", "reason": "unknown mode"})

    report = {
        "command": sys.argv,
        "config": str(args.config),
        "machine": {
            "platform": platform.platform(),
            "kernel": platform.release(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "dataset": dataset,
        "policy": policy,
        "results": results,
        "comparison": comparison(results),
    }
    write_reports(report, args.report_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
