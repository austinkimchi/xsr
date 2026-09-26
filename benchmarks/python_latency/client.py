#!/usr/bin/env python3
"""Open-loop fixed-rate HTTP/1.1 latency client using persistent connections."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import platform
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp

try:
    from .latency import RequestResult, scheduled_time_ns, summarize_requests, worker_for
except ImportError:  # Direct script execution.
    from latency import RequestResult, scheduled_time_ns, summarize_requests, worker_for


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPTS = ROOT / "benchmarks/dataset_prompts.jsonl"
CSV_FIELDS = list(RequestResult.__dataclass_fields__)


@dataclass(slots=True)
class ScheduledRequest:
    sequence: int
    target_ns: int
    payload: bytes
    prompt_index: int
    worker_busy_when_scheduled: bool


class ConnectionCounters:
    def __init__(self) -> None:
        self.created = 0
        self.reused = 0

    async def created_callback(self, *_: Any) -> None:
        self.created += 1

    async def reused_callback(self, *_: Any) -> None:
        self.reused += 1


def load_prompts(path: Path) -> list[bytes]:
    prompts: list[bytes] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"prompt at {path}:{line_number} is not a JSON object")
            payload.pop("x_expected_route", None)
            prompts.append(json.dumps(payload, separators=(",", ":")).encode())
    if not prompts:
        raise ValueError(f"no prompts found in {path}")
    return prompts


def extract_backend(body: bytes) -> str | None:
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    for key in ("backend", "model"):
        marker = value.get(key)
        if marker is not None:
            return str(marker)
    return None


async def sleep_until(target_ns: int) -> None:
    while True:
        remaining_ns = target_ns - time.perf_counter_ns()
        if remaining_ns <= 0:
            return
        await asyncio.sleep(remaining_ns / 1_000_000_000)


async def connection_worker(
    worker_id: int,
    queue: asyncio.Queue[ScheduledRequest | None],
    session: aiohttp.ClientSession,
    available: asyncio.Event,
    *,
    url: str,
    rate: float,
    system: str,
    trial: int,
    results: list[RequestResult] | None,
) -> None:
    while True:
        request = await queue.get()
        if request is None:
            queue.task_done()
            return
        available.clear()
        started_ns = time.perf_counter_ns()
        headers_ns: int | None = None
        completed_ns: int | None = None
        status: int | None = None
        marker: str | None = None
        error_type: str | None = None
        error: str | None = None
        try:
            async with session.post(
                url,
                data=request.payload,
                headers={"Content-Type": "application/json", "Connection": "keep-alive"},
            ) as response:
                headers_ns = time.perf_counter_ns()
                status = response.status
                body = await response.read()
                completed_ns = time.perf_counter_ns()
                marker = extract_backend(body)
        except asyncio.TimeoutError as exc:
            error_type, error = "timeout", f"{type(exc).__name__}: {exc}"
        except aiohttp.ClientConnectionError as exc:
            error_type, error = "connection", f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # Preserve unexpected per-request failures in evidence.
            error_type, error = "other", f"{type(exc).__name__}: {exc}"
        if results is not None:
            results.append(
                RequestResult(
                    trial=trial,
                    system=system,
                    requested_rate=rate,
                    worker_id=worker_id,
                    sequence=request.sequence,
                    prompt_index=request.prompt_index,
                    worker_busy_when_scheduled=request.worker_busy_when_scheduled,
                    scheduled_ns=request.target_ns,
                    request_start_ns=started_ns,
                    response_headers_ns=headers_ns,
                    response_complete_ns=completed_ns,
                    actual_latency_us=(completed_ns - started_ns) / 1_000 if completed_ns else None,
                    scheduling_delay_us=(started_ns - request.target_ns) / 1_000,
                    time_to_headers_us=(headers_ns - started_ns) / 1_000 if headers_ns else None,
                    response_body_us=(completed_ns - headers_ns) / 1_000
                    if completed_ns and headers_ns
                    else None,
                    http_status=status,
                    backend_marker=marker,
                    error_type=error_type,
                    error=error,
                )
            )
        queue.task_done()
        # Stay marked busy when this worker already has overdue work queued.
        if queue.empty():
            available.set()


async def dispatch_phase(
    queues: list[asyncio.Queue[ScheduledRequest | None]],
    availability: list[asyncio.Event],
    prompts: list[bytes],
    *,
    rate: float,
    duration: float,
) -> tuple[int, int]:
    start_ns = time.perf_counter_ns() + 50_000_000
    request_count = int(rate * duration)
    for sequence in range(request_count):
        target_ns = scheduled_time_ns(start_ns, sequence, rate)
        await sleep_until(target_ns)
        prompt_index = sequence % len(prompts)
        worker_id = worker_for(sequence, len(queues))
        await queues[worker_id].put(
            ScheduledRequest(
                sequence,
                target_ns,
                prompts[prompt_index],
                prompt_index,
                not availability[worker_id].is_set(),
            )
        )
    await asyncio.gather(*(queue.join() for queue in queues))
    return start_ns, request_count


async def audit_connections(port: int, output: Path, stop: asyncio.Event) -> None:
    samples: list[dict[str, Any]] = []
    unique: set[str] = set()
    while not stop.is_set():
        process = await asyncio.create_subprocess_exec(
            "ss", "-Hnt", "state", "established", stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        endpoints = []
        for line in stdout.decode(errors="replace").splitlines():
            columns = line.split()
            if len(columns) >= 4 and columns[-1].rsplit(":", 1)[-1] == str(port):
                endpoint = f"{columns[-2]}->{columns[-1]}"
                endpoints.append(endpoint)
                unique.add(endpoint)
        samples.append({"monotonic_ns": time.perf_counter_ns(), "connections": endpoints})
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.1)
        except asyncio.TimeoutError:
            pass
    output.write_text(
        json.dumps(
            {
                "peer_port": port,
                "max_established": max((len(row["connections"]) for row in samples), default=0),
                "unique_connections": sorted(unique),
                "unique_connection_count": len(unique),
                "samples": samples,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


async def benchmark(args: argparse.Namespace) -> tuple[list[RequestResult], dict[str, Any]]:
    prompts = load_prompts(args.prompts)
    queues = [asyncio.Queue() for _ in range(args.connections)]
    availability = [asyncio.Event() for _ in range(args.connections)]
    for event in availability:
        event.set()
    counters = [ConnectionCounters() for _ in range(args.connections)]
    sessions: list[aiohttp.ClientSession] = []
    workers: list[asyncio.Task[None]] = []
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    for worker_id in range(args.connections):
        trace = aiohttp.TraceConfig()
        trace.on_connection_create_end.append(counters[worker_id].created_callback)
        trace.on_connection_reuseconn.append(counters[worker_id].reused_callback)
        connector = aiohttp.TCPConnector(limit=1, limit_per_host=1, force_close=False)
        session = aiohttp.ClientSession(
            connector=connector, timeout=timeout, trace_configs=[trace], auto_decompress=False
        )
        sessions.append(session)
        workers.append(
            asyncio.create_task(
                connection_worker(
                    worker_id,
                    queues[worker_id],
                    session,
                    availability[worker_id],
                    url=args.url,
                    rate=args.rate,
                    system=args.system,
                    trial=args.trial,
                    results=None,
                )
            )
        )

    if args.warmup > 0:
        await dispatch_phase(queues, availability, prompts, rate=args.rate, duration=args.warmup)

    results: list[RequestResult] = []
    # Replace warm-up workers without closing sessions, retaining established TCP connections.
    for queue in queues:
        await queue.put(None)
    await asyncio.gather(*workers)
    workers = [
        asyncio.create_task(
            connection_worker(
                worker_id,
                queues[worker_id],
                sessions[worker_id],
                availability[worker_id],
                url=args.url,
                rate=args.rate,
                system=args.system,
                trial=args.trial,
                results=results,
            )
        )
        for worker_id in range(args.connections)
    ]

    stop_audit = asyncio.Event()
    audit_task: asyncio.Task[None] | None = None
    if args.connection_audit:
        port = urlsplit(args.url).port or (443 if urlsplit(args.url).scheme == "https" else 80)
        audit_task = asyncio.create_task(
            audit_connections(port, args.output_dir / "connection-audit.json", stop_audit)
        )
    start_ns, scheduled = await dispatch_phase(
        queues, availability, prompts, rate=args.rate, duration=args.duration
    )
    if audit_task:
        stop_audit.set()
        await audit_task
    for queue in queues:
        await queue.put(None)
    await asyncio.gather(*workers)
    for session in sessions:
        await session.close()

    results.sort(key=lambda row: row.sequence)
    connection_stats = [
        {"worker_id": index, "connections_created": item.created, "connections_reused": item.reused}
        for index, item in enumerate(counters)
    ]
    return results, {
        "benchmark_start_ns": start_ns,
        "scheduled_requests": scheduled,
        "connection_stats_including_warmup": connection_stats,
        "prompts_loaded": len(prompts),
    }


def write_outputs(
    args: argparse.Namespace, results: list[RequestResult], details: dict[str, Any]
) -> dict[str, Any]:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "requests.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(row.to_dict() for row in results)
    with (args.output_dir / "requests.jsonl").open("w", encoding="utf-8") as output:
        for row in results:
            output.write(json.dumps(row.to_dict(), sort_keys=True) + "\n")

    summary = summarize_requests(results, duration_seconds=args.duration)
    summary.update(
        {
            "trial": args.trial,
            "system": args.system,
            "url": args.url,
            "connections": args.connections,
            "duration_seconds": args.duration,
            "warmup_seconds": args.warmup,
            "expected_interarrival_us": 1_000_000 / args.rate,
            "max_absolute_scheduling_error_us": max(
                (abs(row.scheduling_delay_us) for row in results), default=None
            ),
            **details,
        }
    )
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    provenance = {
        "command": sys.argv,
        "python": sys.version,
        "aiohttp": aiohttp.__version__,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "clock": "time.perf_counter_ns",
        "clock_info": vars(time.get_clock_info("perf_counter")),
        "prompts": str(args.prompts.resolve()),
        "prompts_sha256": hashlib.sha256(args.prompts.read_bytes()).hexdigest(),
    }
    try:
        provenance["git_commit"] = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        provenance["git_commit"] = None
    (args.output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--rate", type=float, required=True)
    parser.add_argument("--connections", type=int, default=4)
    parser.add_argument("--duration", type=float, default=40)
    parser.add_argument("--warmup", type=float, default=3)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--system", required=True)
    parser.add_argument("--trial", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--connection-audit", action="store_true")
    args = parser.parse_args(argv)
    if args.rate <= 0 or args.connections < 1 or args.duration <= 0 or args.warmup < 0:
        parser.error("rate, connections, and duration must be positive; warmup must be non-negative")
    return args


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results, details = asyncio.run(benchmark(args))
    summary = write_outputs(args, results, details)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["completed_requests"] != summary["scheduled_requests"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
