#!/usr/bin/env python3
"""Compare XDP and vLLM-SR on the shared keyword routing policy."""

from __future__ import annotations

import argparse
import concurrent.futures
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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks" / "policy"))

from generate_keyword_header import load_policy, validate_policy  # noqa: E402
from jaccard_reference import rule_matches  # noqa: E402
from bm25_reference import rule_matches as bm25_rule_matches  # noqa: E402


DEFAULT_CONFIG = ROOT / "config" / "policy_ngram.yaml"
DEFAULT_REPORT_DIR = ROOT / "results"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "routing-correctness-benchmark"
DEFAULT_XDP_URL = "http://10.10.0.1:18081/v1/chat/completions"
DEFAULT_VLLM_SR_URL = "http://127.0.0.1:8899/v1/chat/completions"
DEFAULT_VLLM_CODING_BACKEND_PORT = 18391
DEFAULT_VLLM_MATH_BACKEND_PORT = 18392
DEFAULT_VLLM_OTHERS_BACKEND_PORT = 18393
DEFAULT_VLLM_QA_BACKEND_PORT = 18394
DEFAULT_VLLM_WRITING_BACKEND_PORT = 18395
ROUTES = ("coding", "math", "qa", "writing", "others")
ROUTE_HEADERS = (
    "x-vllm-sr-route",
    "x-vsr-selected-decision",
    "x-vsr-selected-model",
    "x-selected-model",
)


DATASETS = {
    "speed-bench": {
        "dataset": "nvidia/SPEED-Bench",
        "config": "qualitative",
        "split": "test",
    },
}
SPEED_BENCH_ROWS = 880
SPEED_CATEGORY_ROUTES = {
    "coding": "coding",
    "math": "math",
    "qa": "qa",
    "writing": "writing",
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
    source_index: int = 0
    xdp_elapsed_ns: int | None = None
    src_port: int | None = None
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
def mock_backend(port: int, backend: str = "others"):
    # A benchmark may be run against a backend started by the surrounding
    # router environment.  Do not fail merely because that endpoint is
    # already available (and do not terminate a process we do not own).
    if socket_open(f"http://127.0.0.1:{port}"):
        print(f"Reusing existing mock/backend listener on port {port}", file=sys.stderr)
        yield
        return

    c_binary = ROOT / "benchmarks" / "mock_backend"
    if c_binary.exists() and os.access(c_binary, os.X_OK):
        proc = subprocess.Popen(
            [str(c_binary), str(port), backend],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.1)
        if proc.poll() is not None:
            stderr = proc.stderr.read().strip() if proc.stderr else ""
            if "Address already in use" in stderr and socket_open(f"http://127.0.0.1:{port}"):
                print(f"Reusing existing mock/backend listener on port {port}", file=sys.stderr)
                yield
                return
            raise RuntimeError(f"mock backend failed to start on port {port}: {stderr or 'unknown error'}")
        try:
            yield
        finally:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=2)
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)
    else:
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
    if "qa" in normalized or "question-answer" in normalized:
        return "qa"
    if "writing" in normalized or "writer" in normalized:
        return "writing"
    if "other" in normalized or "general" in normalized or "default" in normalized:
        return "others"
    return normalized or None


def route_from_headers(headers: dict[str, str]) -> str | None:
    for header in ROUTE_HEADERS:
        route = canonical_route(headers.get(header))
        if route:
            return route
    return None


def route_from_response(headers: dict[str, str], body: bytes) -> str | None:
    route = route_from_headers(headers)
    if route:
        return route
    with contextlib.suppress(json.JSONDecodeError, UnicodeDecodeError):
        payload = json.loads(body)
        if isinstance(payload, dict):
            return canonical_route(payload.get("backend"))
    return None


def send_case(url: str, case: Case, timeout_s: float) -> Result:
    parsed = urllib.parse.urlparse(chat_url(url))
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    start = time.perf_counter_ns()
    src_port: int | None = None
    try:
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout_s)
        conn.connect()
        if conn.sock:
            src_port = conn.sock.getsockname()[1]
        conn.request(
            "POST",
            path,
            body=chat_body(case.prompt),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        body = response.read()
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        headers = {key.lower(): value for key, value in response.getheaders()}
        return Result(
            case.prompt,
            case.expected_route,
            response.status,
            elapsed_ms,
            route_from_response(headers, body),
            case.matched_keyword,
            source_index=case.source_index,
            src_port=src_port,
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
            source_index=case.source_index,
            src_port=src_port,
            error=str(exc),
        )
    finally:
        with contextlib.suppress(Exception):
            conn.close()  # type: ignore[name-defined]


_thread_local = threading.local()


def get_thread_connection(hostname: str, port: int, timeout_s: float) -> http.client.HTTPConnection:
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = http.client.HTTPConnection(hostname, port, timeout=timeout_s)
        conn.connect()
        _thread_local.conn = conn
    return conn


def send_case_persistent(url: str, case: Case, timeout_s: float) -> Result:
    parsed = urllib.parse.urlparse(chat_url(url))
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    start = time.perf_counter_ns()
    src_port: int | None = None
    try:
        conn = get_thread_connection(parsed.hostname, parsed.port or 80, timeout_s)
        if conn.sock:
            src_port = conn.sock.getsockname()[1]
        conn.request(
            "POST",
            path,
            body=chat_body(case.prompt),
            headers={"Content-Type": "application/json", "Connection": "keep-alive"},
        )
        response = conn.getresponse()
        body = response.read()
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        headers = {key.lower(): value for key, value in response.getheaders()}
        return Result(
            case.prompt,
            case.expected_route,
            response.status,
            elapsed_ms,
            route_from_response(headers, body),
            case.matched_keyword,
            source_index=case.source_index,
            src_port=src_port,
        )
    except Exception:
        with contextlib.suppress(Exception):
            if hasattr(_thread_local, "conn"):
                _thread_local.conn.close()
                delattr(_thread_local, "conn")
        return send_case(url, case, timeout_s)


def send_cases_concurrently(url: str, cases: list[Case], timeout_s: float, concurrency: int) -> list[Result]:
    if concurrency <= 1:
        # SOCKMAP binds a client connection to five backend sockets. Reuse the
        # connection for serial runs so the benchmark does not turn every
        # request into a new long-lived SOCKMAP connection set.
        return [send_case_persistent(url, case, timeout_s) for case in cases]
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(send_case_persistent, url, case, timeout_s) for case in cases]
        return [future.result() for future in futures]


def run_client_worker(url: str, timeout_s: float, concurrency: int = 1) -> int:
    cases = []
    for line in sys.stdin:
        if not line.strip():
            continue
        item = json.loads(line)
        cases.append(
            Case(
                item["prompt"],
                item["expected_route"],
                item.get("matched_keyword"),
                item.get("source_index", 0),
            )
        )
    results = send_cases_concurrently(url, cases, timeout_s, concurrency)
    for result in results:
        print(json.dumps(dataclasses.asdict(result), separators=(",", ":")), flush=True)
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
            url = f"https://datasets-server.huggingface.co/rows?{query}"
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "xdp-router-benchmark/1.0"},
            )
            for attempt in range(6):
                try:
                    with urllib.request.urlopen(request, timeout=60) as response:
                        data = json.load(response)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code != 429 or attempt == 5:
                        raise
                    retry_after = exc.headers.get("Retry-After")
                    try:
                        sleep_s = float(retry_after) if retry_after else 2**attempt
                    except ValueError:
                        sleep_s = 2**attempt
                    print(
                        f"Rate limited by Hugging Face rows API; retrying in {sleep_s:.1f}s...",
                        file=sys.stderr,
                    )
                    time.sleep(sleep_s)
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
        "requested_per_route": getattr(args, "per_route", None),
    }


def expected_route(
    prompt: str,
    routes: list[dict[str, object]],
    case_sensitive: bool,
) -> tuple[str, str | None]:
    for route in routes:
        method = str(route.get("method", "")).lower()
        keywords = [str(keyword) for keyword in route["keywords"]]  # type: ignore[index]
        operator = str(route.get("operator", "OR"))
        if method == "ngram":
            arity = int(route.get("ngram_arity", 3))
            threshold = route.get("ngram_threshold", 0.4)
            matched = rule_matches(prompt, keywords, operator, arity, threshold, case_sensitive)
            single_match = lambda keyword: rule_matches(prompt, [keyword], "OR", arity, threshold, case_sensitive)
        elif method == "bm25":
            threshold = route.get("bm25_threshold", 0.1)
            matched = bm25_rule_matches(prompt, keywords, operator, threshold)
            single_match = lambda keyword: bm25_rule_matches(prompt, [keyword], "OR", threshold)
        else:
            raise ValueError(f"benchmark policy uses unsupported method {method!r}")
        if not matched:
            continue
        matching_keyword = next(
            (
                keyword
                for keyword in keywords
                if single_match(keyword)
            ),
            None,
        )
        return str(route["name"]), matching_keyword
    return "others", None


def select_cases(
    rows: list[dict[str, Any]],
    routes: list[dict[str, object]],
    case_sensitive: bool,
    per_route: int | None,
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
        if per_route is None or len(buckets[route]) < per_route:
            buckets[route].append(Case(prompt, route, keyword, index))
        if per_route is not None and all(len(buckets[route]) >= per_route for route in ROUTES):
            break

    cases = [case for route in ROUTES for case in buckets[route]]
    counts.update({route: len(buckets[route]) for route in ROUTES})
    if per_route is not None and any(counts[route] < per_route for route in ROUTES):
        missing = ", ".join(f"{route}={counts[route]}" for route in ROUTES)
        raise SystemExit(f"not enough dataset prompts for requested sample: {missing}")
    return cases, counts


def load_speed_bench_cases(args: argparse.Namespace) -> tuple[list[Case], dict[str, Any]]:
    """Load every qualitative SPEED-Bench request with its category route label."""
    rows, meta = load_rows(args)
    if len(rows) != SPEED_BENCH_ROWS:
        raise SystemExit(
            f"SPEED-Bench qualitative/test must contain {SPEED_BENCH_ROWS} rows; got {len(rows)}"
        )

    cases: list[Case] = []
    selected = {route: 0 for route in ROUTES}
    selected.update({"embedded_quote": 0, "duplicate_prompt": 0, "missing_prompt": 0})
    categories: dict[str, int] = {}
    for index, row in enumerate(rows):
        prompt = prompt_from_row(row)
        if not prompt:
            raise SystemExit(f"SPEED-Bench row {index} has no usable prompt")
        category = str(row.get("category", "")).strip().lower()
        if not category:
            raise SystemExit(f"SPEED-Bench row {index} has no category")
        route = SPEED_CATEGORY_ROUTES.get(category, "others")
        cases.append(Case(prompt, route, None, index))
        selected[route] += 1
        categories[category] = categories.get(category, 0) + 1

    expected_counts = {"coding": 80, "math": 80, "qa": 80, "writing": 80, "others": 560}
    if selected != {**expected_counts, "embedded_quote": 0, "duplicate_prompt": 0, "missing_prompt": 0}:
        raise SystemExit(f"unexpected SPEED-Bench route distribution: {selected}")
    meta["selected_counts"] = selected
    meta["categories"] = categories
    meta["all_rows_required"] = SPEED_BENCH_ROWS
    return cases, meta


def load_cases(args: argparse.Namespace) -> tuple[list[Case], dict[str, Any], dict[str, Any]]:
    policy = load_policy(args.config)
    case_sensitive, routes = validate_policy(policy)
    cases, meta = load_speed_bench_cases(args)
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


def summarize(
    mode: str,
    results: list[Result],
    wall_s: float,
    host_cpu: float | None,
    cpu: float | None,
    expected_requests: int | None = None,
) -> dict[str, Any]:
    latencies = [result.elapsed_ms for result in results if result.status and not result.error]
    correct = sum(1 for result in results if result.route == result.expected_route)
    counts = {route: 0 for route in ROUTES}
    counts["unknown"] = 0
    for result in results:
        counts[result.route if result.route in ROUTES else "unknown"] += 1

    xdp_ns = [result.xdp_elapsed_ns for result in results if result.xdp_elapsed_ns is not None]
    observations = [
        {
            **dataclasses.asdict(result),
            "reference_route_match": result.route == result.expected_route,
        }
        for result in results
    ]
    return {
        "mode": mode,
        "status": "ok",
        "requests": len(results),
        "expected_requests": len(results) if expected_requests is None else expected_requests,
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
        # Keep each observation and its label match so XDP and vLLM-SR can be
        # compared request-for-request, not inferred from aggregate counts.
        "results": observations,
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
    results = send_cases_concurrently(args.vllm_sr_url, cases, args.timeout_s, args.concurrency)
    wall_s = time.perf_counter() - start
    return summarize(
        "vllm-sr",
        results,
        wall_s,
        cpu_delta(cpu_start, read_cpu()),
        sampled_cpu(containers=("vllm-sr-router-container", "vllm-sr-envoy-container")),
        len(cases),
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
        # The benchmark reference matcher and the XDP maps must be generated
        # from the exact same policy file, including when --config is custom.
        checked(["make", f"KEYWORD_POLICY={args.config.resolve()}", "dev"])
    subprocess.run(["ip", "link", "set", "dev", args.xdp_ifname, "xdp", "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
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


def sanitize_benchmark_processes() -> None:
    """Release fixed benchmark ports from processes left by an earlier run."""
    process_names = ("sk_router", "xdp_router", "mock_backend")
    for name in process_names:
        subprocess.run(
            ["pkill", "-TERM", "-x", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        still_running = any(
            subprocess.run(
                ["pgrep", "-x", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
            for name in process_names
        )
        if not still_running:
            return
        time.sleep(0.05)

    for name in process_names:
        subprocess.run(
            ["pkill", "-KILL", "-x", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def read_router(router: subprocess.Popen[str], out: queue.Queue[str]) -> None:
    if router.stdout:
        for line in router.stdout:
            out.put(line.rstrip())


def wait_for_router(
    router: subprocess.Popen[str],
    out: queue.Queue[str],
    ready_line: str,
    observed: list[str] | None = None,
) -> bool:
    deadline = time.time() + 10
    while time.time() < deadline:
        if router.poll() is not None:
            return False
        try:
            line = out.get(timeout=0.1)
            if observed is not None:
                observed.append(line)
            if ready_line in line:
                return True
        except queue.Empty:
            pass
    return False


def drain_output(out: queue.Queue[str], limit: int = 20) -> list[str]:
    lines: list[str] = []
    while len(lines) < limit:
        try:
            lines.append(out.get_nowait())
        except queue.Empty:
            break
    return lines


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
            "--concurrency",
            str(args.concurrency),
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
        # communicate reads stdout while feeding stdin. Writing the complete
        # case set first and only then reading results can deadlock when either
        # pipe fills (especially with large prompts or many cases).
        payload = "".join(
            json.dumps(dataclasses.asdict(case), separators=(",", ":")) + "\n"
            for case in cases
        )
        batches = (len(cases) + max(args.concurrency, 1) - 1) // max(args.concurrency, 1)
        worker_timeout_s = max(15, batches * args.timeout_s + 10)
        try:
            stdout, stderr = worker.communicate(payload, timeout=worker_timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"netns client timed out after {worker_timeout_s:.1f}s "
                f"for {len(cases)} cases"
            ) from exc
        if worker.returncode != 0:
            raise RuntimeError(stderr.strip() or f"netns client exited with {worker.returncode}")

        results = [Result(**json.loads(line)) for line in stdout.splitlines() if line.strip()]
        if len(results) != len(cases):
            detail = stderr.strip() or f"got {len(results)} results for {len(cases)} cases"
            raise RuntimeError(f"netns client returned incomplete results: {detail}")
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

        summary = summarize("direct-netns", results, wall_s, host_cpu, None, len(cases))
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
        startup_logs: list[str] = []
        if not wait_for_router(router, out, "XDP attached", startup_logs):
            logs = startup_logs + drain_output(out)
            reason = "xdp_router did not attach"
            if logs:
                reason = f"{reason}: {'; '.join(logs[-5:])}"
            return {"mode": "xdp", "status": "skipped", "reason": reason}

        cpu_start = read_cpu()
        start = time.perf_counter()
        results = netns_requests(args, cases)
        wall_s = time.perf_counter() - start
        host_cpu = cpu_delta(cpu_start, read_cpu())
        events = route_events(out, len(results), args.event_timeout_s)
        events_by_port: dict[int, list[dict[str, Any]]] = {}
        for event in events:
            if "src_port" in event:
                port = int(event["src_port"])
                events_by_port.setdefault(port, []).append(event)

        for index, result in enumerate(results):
            event = None
            if result.src_port and events_by_port.get(result.src_port):
                event = events_by_port[result.src_port].pop(0)
            elif not result.src_port and index < len(events):
                event = events[index]
            if event:
                result.route = canonical_route(event.get("route_name"))
                result.xdp_elapsed_ns = event.get("xdp_elapsed_ns")

        summary = summarize("xdp", results, wall_s, host_cpu, sampled_cpu(pid=router.pid), len(cases))
        summary["route_events"] = len(events)
        summary["missing_route_events"] = max(0, len(results) - len(events))
        if len(events) < len(results):
            summary["status"] = "incomplete"
            summary["reason"] = f"received {len(events)} XDP route events for {len(results)} client responses"
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


def run_sockmap(args: argparse.Namespace, cases: list[Case]) -> dict[str, Any]:
    if os.geteuid() != 0:
        return {"mode": "xdp", "execution_mode": "sockmap", "status": "skipped", "reason": "SOCKMAP mode requires root"}
    if not shutil.which("ip"):
        return {"mode": "xdp", "execution_mode": "sockmap", "status": "skipped", "reason": "iproute2 is required"}
    if args.setup:
        checked(["make", "setup"])
    try:
        checked(["ip", "netns", "exec", args.xdp_netns, "true"])
    except subprocess.CalledProcessError:
        return {"mode": "xdp", "execution_mode": "sockmap", "status": "skipped", "reason": "missing prerequisite: network namespace"}
    if not args.no_build:
        checked(["make", f"KEYWORD_POLICY={args.config.resolve()}", "dev"])

    router: subprocess.Popen[str] | None = None
    firewall = False
    out: queue.Queue[str] = queue.Queue()
    try:
        if not args.no_firewall:
            iptables_allow(args.xdp_ifname, args.xdp_backend_port)
            firewall = True
        router = subprocess.Popen(
            [str(ROOT / "sk_router")],
            cwd=ROOT,
            env={**os.environ, "SK_ROUTER_MODE": "sockmap"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=read_router, args=(router, out), daemon=True).start()
        startup_logs: list[str] = []
        if not wait_for_router(router, out, "SK_SKB router listening", startup_logs):
            logs = startup_logs + drain_output(out)
            reason = "sk_router did not start in SOCKMAP mode"
            if logs:
                reason = f"{reason}: {'; '.join(logs[-5:])}"
            return {"mode": "xdp", "execution_mode": "sockmap", "status": "skipped", "reason": reason}

        cpu_start = read_cpu()
        start = time.perf_counter()
        results = netns_requests(args, cases)
        wall_s = time.perf_counter() - start
        # The SOCKMAP program is the in-kernel XDP-path result reported to users.
        summary = summarize("xdp", results, wall_s, cpu_delta(cpu_start, read_cpu()), sampled_cpu(pid=router.pid), len(cases))
        summary["execution_mode"] = "sockmap"
        unknown = summary["route_counts"]["unknown"]
        if summary["errors"] or unknown:
            summary["status"] = "incomplete"
            summary["reason"] = f"errors={summary['errors']}, unknown_routes={unknown}"
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


def xsr_vsr_routing_agreement(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare XDP (XSR) and vLLM-SR routes for the exact same prompts.

    This intentionally does not derive equivalence from either system's
    agreement with the reference label: two systems can have the same
    reference score while disagreeing on individual prompts.
    """
    by_mode = {item.get("mode"): item for item in results}
    xsr = by_mode.get("xdp")
    vsr = by_mode.get("vllm-sr")
    if not xsr or not vsr:
        return {"status": "incomplete", "reason": "both xdp and vllm-sr modes must be run"}
    if xsr.get("status") != "ok" or vsr.get("status") != "ok":
        return {
            "status": "incomplete",
            "reason": "both xdp and vllm-sr modes must complete",
            "xsr_status": xsr.get("status"),
            "vsr_status": vsr.get("status"),
        }

    def index_mode(mode_result: dict[str, Any], name: str) -> tuple[dict[tuple[int, str], dict[str, Any]] | None, str | None]:
        observations = mode_result.get("results")
        if not isinstance(observations, list):
            return None, f"{name} did not retain per-prompt results"
        expected_requests = mode_result.get("expected_requests", mode_result.get("requests"))
        if not isinstance(expected_requests, int) or len(observations) != expected_requests:
            return None, f"{name} returned {len(observations)} of {expected_requests} expected prompt results"
        indexed: dict[tuple[int, str], dict[str, Any]] = {}
        for observation in observations:
            if not isinstance(observation, dict) or not isinstance(observation.get("prompt"), str):
                return None, f"{name} contains an invalid per-prompt result"
            key = (observation.get("source_index", 0), observation["prompt"])
            if key in indexed:
                return None, f"{name} has duplicate prompt identity at source index {key[0]}"
            indexed[key] = observation
        return indexed, None

    xsr_by_prompt, error = index_mode(xsr, "xdp")
    if error:
        return {"status": "incomplete", "reason": error}
    vsr_by_prompt, error = index_mode(vsr, "vllm-sr")
    if error:
        return {"status": "incomplete", "reason": error}
    assert xsr_by_prompt is not None and vsr_by_prompt is not None

    xsr_keys = set(xsr_by_prompt)
    vsr_keys = set(vsr_by_prompt)
    if xsr_keys != vsr_keys:
        missing_from_xsr = sorted(vsr_keys - xsr_keys)
        missing_from_vsr = sorted(xsr_keys - vsr_keys)
        return {
            "status": "incomplete",
            "reason": "one or more prompts are missing from a mode",
            "missing_from_xsr": len(missing_from_xsr),
            "missing_from_vsr": len(missing_from_vsr),
            "missing_prompt_identities": {
                "from_xsr": [{"source_index": index, "prompt": prompt[:160]} for index, prompt in missing_from_xsr[:10]],
                "from_vsr": [{"source_index": index, "prompt": prompt[:160]} for index, prompt in missing_from_vsr[:10]],
            },
        }

    missing_routes = [
        {"source_index": key[0], "prompt": key[1][:160], "mode": mode}
        for mode, observations in (("xsr", xsr_by_prompt), ("vsr", vsr_by_prompt))
        for key, observation in observations.items()
        if observation.get("route") not in ROUTES
    ]
    if missing_routes:
        return {
            "status": "incomplete",
            "reason": "one or more prompts have no recognized route decision",
            "missing_route_count": len(missing_routes),
            "missing_routes": missing_routes[:10],
        }

    matrix = {xsr_route: {vsr_route: 0 for vsr_route in ROUTES} for xsr_route in ROUTES}
    request_comparisons: list[dict[str, Any]] = []
    agreements = 0
    for key in sorted(xsr_keys):
        xsr_result = xsr_by_prompt[key]
        vsr_result = vsr_by_prompt[key]
        if xsr_result.get("expected_route") != vsr_result.get("expected_route"):
            return {
                "status": "incomplete",
                "reason": "modes disagree on the expected route for a request",
                "source_index": key[0],
                "prompt": key[1][:160],
            }
        xsr_route = xsr_result["route"]
        vsr_route = vsr_result["route"]
        matrix[xsr_route][vsr_route] += 1
        routes_match = xsr_route == vsr_route
        request_comparisons.append(
            {
                "source_index": key[0],
                "prompt": key[1],
                "expected_route": xsr_result["expected_route"],
                "xdp_route": xsr_route,
                "vllm_sr_route": vsr_route,
                "routes_match": routes_match,
                "xdp_reference_match": xsr_result.get("reference_route_match"),
                "vllm_sr_reference_match": vsr_result.get("reference_route_match"),
            }
        )
        if routes_match:
            agreements += 1

    total = len(xsr_keys)
    return {
        "status": "ok",
        "total": total,
        "agreement_count": agreements,
        "agreement_percent": 100.0 * agreements / total if total else None,
        "confusion_matrix": matrix,
        "request_comparisons": request_comparisons,
        "mismatches": [comparison for comparison in request_comparisons if not comparison["routes_match"]],
    }


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def get_report_filename(report_name_arg: str | None = None) -> str:
    if report_name_arg:
        return report_name_arg if report_name_arg.endswith(".md") else f"{report_name_arg}.md"
    return "routing_correctness_benchmark.md"


def chown_reports_to_invoking_user(report_dir: Path, report_paths: list[Path]) -> None:
    """Return sudo-created reports to the user who invoked `make correctness`."""
    if os.geteuid() != 0:
        return
    try:
        uid = int(os.environ["SUDO_UID"])
        gid = int(os.environ["SUDO_GID"])
    except (KeyError, ValueError):
        return

    for path in (report_dir, *report_paths):
        os.chown(path, uid, gid)


def write_reports(
    report: dict[str, Any],
    report_dir: Path,
    report_name: str = "routing_correctness_benchmark.md",
    write_json: bool = False,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    written_paths = [report_dir / report_name]
    if write_json:
        json_name = f"{Path(report_name).stem}.json"
        json_path = report_dir / json_name
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        written_paths.append(json_path)

    dataset = report["dataset"]
    selected = dataset["selected_counts"]
    control_results = [r for r in report["results"] if r.get("mode") in {"direct-netns", "direct"}]
    test_results = [r for r in report["results"] if r.get("mode") not in {"direct-netns", "direct"}]

    concurrency = report.get("concurrency", 1)
    lines = [
        "# SPEED-Bench Routing Correctness Benchmark",
        "",
        f"- Dataset: `{dataset['source']}`",
        f"- Total rows: {dataset['scanned_rows']}",
        "- Selected prompts: " + ", ".join(f"{route}={selected[route]}" for route in ROUTES),
        f"- Rows excluded: embedded_quote={selected['embedded_quote']}, duplicate_prompt={selected['duplicate_prompt']}, missing_prompt={selected['missing_prompt']}",
        f"- Policy: case_sensitive={report['policy']['case_sensitive']}; keywords={report['policy']['keyword_count']}",
        f"- Concurrency: {concurrency}",
        "",
    ]
    if dataset.get("sources"):
        lines += [
            "## Dataset Mix",
            "",
            "| Source | Scanned | coding | math | qa | writing | others |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for source in dataset["sources"]:
            counts = source["selected_counts"]
            lines.append(
                f"| `{source['source']}` | {source['scanned_rows']} | "
                + " | ".join(str(counts[route]) for route in ROUTES)
                + " |"
            )
        lines.append("")

    if control_results:
        lines += [
            "## Control Result",
            "",
            "| Mode | Requests | avg ms | p99 ms | RPS | Host CPU % | Sampled CPU % |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for result in control_results:
            if result.get("status") != "ok":
                lines.append(f"| {result['mode']} ({result.get('reason', 'skipped')}) | 0 | n/a | n/a | n/a | n/a | n/a |")
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
        "| Mode | Requests | Reference-label agreement | avg ms | p99 ms | RPS | Host CPU % | Sampled CPU % |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in test_results:
        if result.get("status") != "ok":
            lines.append(f"| {result['mode']} ({result.get('reason', result.get('status', 'skipped'))}) | {result.get('requests', 0)} | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        latency = result["latency_ms"]
        lines.append(
            f"| {result['mode']} | {result['requests']} | {fmt(result['route_agreement'], 4)} | "
            f"{fmt(latency['avg'])} | {fmt(latency['p99'])} | "
            f"{fmt(result['requests_per_second'])} | {fmt(result['host_cpu_percent'])} | {fmt(result['sampled_cpu_percent'])} |"
        )

    pairwise = report["xsr_vsr_routing_agreement"]
    lines += ["", "## XSR vs VSR Routing Agreement", ""]
    if pairwise["status"] == "ok":
        lines += [
            f"XSR ↔ VSR agreement: {pairwise['agreement_count']}/{pairwise['total']} ({pairwise['agreement_percent']:.2f}%)",
            "",
            "```text",
            "             VSR",
            "           " + " ".join(f"{route:>7}" for route in ROUTES),
            *[
                f"XSR {route:<7}" + " ".join(f"{pairwise['confusion_matrix'][route][target]:>7}" for target in ROUTES)
                for route in ROUTES
            ],
            "```",
        ]
        mismatches = pairwise["mismatches"]
        if mismatches:
            lines += [
                "",
                "### Per-Request Route Mismatches",
                "",
                "| Source index | Expected | XDP | vLLM-SR | Prompt |",
                "| ---: | --- | --- | --- | --- |",
            ]
            for item in mismatches[:20]:
                prompt = " ".join(item["prompt"].split())[:160].replace("|", "\\|")
                lines.append(
                    f"| {item['source_index']} | {item['expected_route']} | {item['xdp_route']} | "
                    f"{item['vllm_sr_route']} | {prompt} |"
                )
            if len(mismatches) > 20:
                lines.append(f"\n- Showing 20 of {len(mismatches)} request mismatches; all are in the JSON report.")
    else:
        lines.append(f"- Pairwise comparison incomplete: {pairwise.get('reason', 'unknown')}")

    lines += [
        "",
        "## Route Counts",
        "",
        "| Mode | " + " | ".join(ROUTES) + " |",
        "| --- | " + " | ".join("---:" for _ in ROUTES) + " |",
    ]
    for result in test_results:
        counts = result.get("route_counts") or {}
        lines.append(f"| {result['mode']} | " + " | ".join(str(counts.get(route, 0)) for route in ROUTES) + " |")

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
            f"- Reference-label agreement delta, XDP minus vLLM-SR: {fmt(comp['route_agreement_delta'], 4)}",
            f"- Average latency delta, XDP minus vLLM-SR: {fmt(comp['avg_latency_delta_ms'])} ms",
            f"- p99 latency delta, XDP minus vLLM-SR: {fmt(comp['p99_latency_delta_ms'])} ms",
        ]
    else:
        lines.append(f"- Comparison incomplete: {comp.get('reason', 'unknown')}")

    report_path = report_dir / report_name
    report_path.write_text("\n".join(lines) + "\n")
    chown_reports_to_invoking_user(report_dir, written_paths)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-worker")
    parser.add_argument("-c", "--concurrency", type=int, default=1, help="Number of concurrent client workers / connections")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--dataset",
        choices=sorted(DATASETS),
        default="speed-bench",
        help="SPEED-Bench qualitative/test is the required routing-correctness corpus.",
    )
    parser.add_argument("--scan-limit", type=int, default=SPEED_BENCH_ROWS, help="Must be at least 880 for SPEED-Bench.")
    parser.add_argument("--per-route", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--report-name", default=None, help="Markdown report filename (default: routing_correctness_benchmark.md)")
    parser.add_argument("--json-output", action="store_true", help="Also write a JSON report alongside the Markdown report")
    parser.add_argument("--modes", default="direct-netns,xdp,vllm-sr")
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--event-timeout-s", type=float, default=10.0)
    parser.add_argument("--xdp-url", default=DEFAULT_XDP_URL)
    parser.add_argument("--xdp-ifname", default="veth0")
    parser.add_argument("--xdp-netns", default="ns1")
    parser.add_argument("--xdp-backend-port", type=int, default=18081)
    parser.add_argument("--vllm-sr-url", default=DEFAULT_VLLM_SR_URL)
    parser.add_argument(
        "--vllm-backend-port",
        type=int,
        default=DEFAULT_VLLM_CODING_BACKEND_PORT,
        help="Mock vLLM-SR coding backend port",
    )
    parser.add_argument(
        "--vllm-math-backend-port",
        type=int,
        default=DEFAULT_VLLM_MATH_BACKEND_PORT,
        help="Mock vLLM-SR math backend port",
    )
    parser.add_argument(
        "--vllm-others-backend-port",
        type=int,
        default=DEFAULT_VLLM_OTHERS_BACKEND_PORT,
        help="Mock vLLM-SR others backend port",
    )
    parser.add_argument("--vllm-qa-backend-port", type=int, default=DEFAULT_VLLM_QA_BACKEND_PORT, help="Mock vLLM-SR QA backend port")
    parser.add_argument("--vllm-writing-backend-port", type=int, default=DEFAULT_VLLM_WRITING_BACKEND_PORT, help="Mock vLLM-SR writing backend port")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--no-firewall", action="store_true")
    parser.add_argument("--no-mock-backends", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.client_worker:
        return run_client_worker(args.client_worker, args.timeout_s, args.concurrency)
    if os.geteuid() != 0:
        print("Routing correctness benchmark requires root privileges. Elevating with sudo...", file=sys.stderr)
        os.execvp("sudo", ["sudo", sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])

    cases, dataset, policy = load_cases(args)
    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    results: list[dict[str, Any]] = []

    if {"direct-netns", "xdp", "sockmap"}.intersection(modes):
        sanitize_benchmark_processes()

    for mode in modes:
        # The direct control's mock occupies the same frontend port as both
        # routers. Scope fixtures to one mode so it is gone before SOCKMAP
        # starts listening on 18081.
        with contextlib.ExitStack() as stack:
            if not args.no_mock_backends:
                if mode == "direct-netns":
                    stack.enter_context(mock_backend(args.xdp_backend_port, "others"))
                elif mode in {"sockmap", "vllm-sr"}:
                    for port, backend in (
                        (args.vllm_backend_port, "coding"),
                        (args.vllm_math_backend_port, "math"),
                        (args.vllm_others_backend_port, "others"),
                        (args.vllm_qa_backend_port, "qa"),
                        (args.vllm_writing_backend_port, "writing"),
                    ):
                        stack.enter_context(mock_backend(port, backend))
            if mode == "direct-netns":
                results.append(run_direct_netns(args, cases))
            elif mode == "xdp":
                results.append(run_xdp(args, cases))
            elif mode == "sockmap":
                results.append(run_sockmap(args, cases))
            elif mode == "vllm-sr":
                results.append(run_vllm(args, cases))
            else:
                results.append({"mode": mode, "status": "skipped", "reason": "unknown mode"})

    report = {
        "command": sys.argv,
        "config": str(args.config),
        "concurrency": args.concurrency,
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
        "xsr_vsr_routing_agreement": xsr_vsr_routing_agreement(results),
    }
    md_name = get_report_filename(args.report_name)
    write_reports(report, args.report_dir, md_name, args.json_output)
    print(f"Wrote {args.report_dir / md_name}")
    if args.json_output:
        print(f"Wrote {args.report_dir / f'{Path(md_name).stem}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
