#!/usr/bin/env python3
"""Compile raw wrk and correctness reports into results/wrk_benchmark.md."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = ROOT / "results"
PERFORMANCE_CONCURRENCIES = (1, 2, 4, 8, 10, 16, 32, 64, 96)
CORRECTNESS_CONCURRENCIES = (1, 4, 8, 16)


@dataclass(frozen=True)
class PerformanceResult:
    concurrency: int
    timestamp: str
    duration: str
    xdp_rps: float
    xdp_latency: str
    vllm_rps: float
    vllm_latency: str
    xdp_marker_agreement: float
    xdp_fifo_agreement: float
    vllm_marker_agreement: float
    vllm_fifo_agreement: float


@dataclass(frozen=True)
class CorrectnessResult:
    concurrency: int
    xdp_avg: float
    xdp_p99: float
    xdp_rps: float
    vllm_avg: float
    vllm_p99: float
    vllm_rps: float
    agreement_count: int
    agreement_total: int
    agreement_percent: float


def required_match(pattern: str, text: str, description: str) -> re.Match[str]:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError(f"missing {description}")
    return match


def section(text: str, headings: tuple[str, ...]) -> tuple[str, str]:
    for heading in headings:
        start = text.find(heading)
        if start >= 0:
            break
    else:
        raise ValueError(f"missing section: {' or '.join(headings)}")
    end = text.find("\n## ", start + len(heading))
    return heading, text[start:] if end < 0 else text[start:end]


def parse_route_section(text: str, headings: tuple[str, ...]) -> tuple[float, str, float, float]:
    heading, route = section(text, headings)
    latency = required_match(r"^\s*Latency\s+(\S+)", route, f"{heading} average latency").group(1)
    rps = float(required_match(r"^Requests/sec:\s+([0-9.]+)", route, f"{heading} requests/s").group(1))
    marker = required_match(
        r"aggregate route agreement:\s+([0-9.]+).*?fifo_matches=(\d+)\s+fifo_mismatches=(\d+)",
        route,
        f"{heading} routing markers",
    )
    fifo_matches, fifo_mismatches = int(marker.group(2)), int(marker.group(3))
    fifo_total = fifo_matches + fifo_mismatches
    fifo_agreement = fifo_matches / fifo_total if fifo_total else 0.0
    return rps, latency, float(marker.group(1)), fifo_agreement


def parse_performance(path: Path) -> PerformanceResult:
    text = path.read_text()
    concurrency = int(required_match(r"^- Connections: `(\d+)`", text, "connection count").group(1))
    timestamp = required_match(r"^- Timestamp: `([^`]+)`", text, "timestamp").group(1)
    duration = required_match(r"^- Duration: `([^`]+)`", text, "duration").group(1)
    xdp_rps, xdp_latency, xdp_marker, xdp_fifo = parse_route_section(
        text,
        ("## [2/3] XSR Route", "## [3/4] XSR Route", "## [2/4] XSR/XDP Route"),
    )
    vllm_rps, vllm_latency, vllm_marker, vllm_fifo = parse_route_section(
        text,
        ("## [3/3] vLLM-SR Route", "## [4/4] vLLM-SR Route"),
    )
    return PerformanceResult(
        concurrency, timestamp, duration, xdp_rps, xdp_latency, vllm_rps, vllm_latency,
        xdp_marker, xdp_fifo, vllm_marker, vllm_fifo,
    )


def parse_correctness(path: Path) -> CorrectnessResult:
    text = path.read_text()
    concurrency = int(required_match(r"^- Concurrency: (\d+)", text, "concurrency").group(1))

    def row(mode: str) -> tuple[float, float, float]:
        match = required_match(
            rf"^\| {re.escape(mode)} \| \d+ \| [0-9.]+ \| ([0-9.]+) \| ([0-9.]+) \| ([0-9.]+) \|",
            text,
            f"{mode} result row",
        )
        return float(match.group(1)), float(match.group(2)), float(match.group(3))

    xdp_avg, xdp_p99, xdp_rps = row("xdp")
    vllm_avg, vllm_p99, vllm_rps = row("vllm-sr")
    agreement = required_match(r"XSR ↔ VSR agreement: (\d+)/(\d+) \(([0-9.]+)%\)", text, "routing agreement")
    return CorrectnessResult(
        concurrency, xdp_avg, xdp_p99, xdp_rps, vllm_avg, vllm_p99, vllm_rps,
        int(agreement.group(1)), int(agreement.group(2)), float(agreement.group(3)),
    )


def display_timestamp(value: str) -> str:
    match = required_match(
        r"^\w+ (\w+) (\d+) (\d\d:\d\d:\d\d [AP]M) (\w+) (\d{4})$",
        value,
        "timestamp format",
    )
    month, day, clock, timezone, year = match.groups()
    full_months = {
        "Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
        "May": "May", "Jun": "June", "Jul": "July", "Aug": "August",
        "Sep": "September", "Oct": "October", "Nov": "November", "Dec": "December",
    }
    return f"{full_months[month]} {int(day)}, {year} at {clock} {timezone}"


def display_latency(value: str) -> str:
    match = required_match(r"^([0-9.]+)([a-z]+)$", value, "latency value")
    return f"{float(match.group(1)):.2f} {match.group(2)}"


def percentage_range(values: list[float]) -> str:
    return f"{min(values) * 100:.2f}%–{max(values) * 100:.2f}%"


def compile_report(results_dir: Path, output: Path) -> None:
    performance_dir = results_dir / "routing-performance"
    correctness_dir = results_dir / "routing-correctness"
    performance = [parse_performance(performance_dir / f"routing_performance_{value}.md") for value in PERFORMANCE_CONCURRENCIES]
    correctness = [
        parse_correctness(correctness_dir / f"routing_correctness_benchmark_concurrency_{value}.md")
        for value in CORRECTNESS_CONCURRENCIES
    ]

    durations = {result.duration for result in performance}
    if len(durations) != 1:
        raise ValueError(f"performance reports use different durations: {', '.join(sorted(durations))}")

    lines = [
        "# XDP vs. vLLM-SR benchmark summary",
        "",
        f"- Ran on {display_timestamp(performance[0].timestamp)}",
        f"- Duration of test: {durations.pop()} per concurrency level",
        "",
        "| Concurrency | XDP requests/s | XDP average latency | vLLM-SR requests/s | vLLM-SR average latency | XDP throughput advantage | XDP latency advantage |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in performance:
        lines.append(
            f"| {result.concurrency} | {result.xdp_rps:,.2f} | {display_latency(result.xdp_latency)} | "
            f"{result.vllm_rps:,.2f} | {display_latency(result.vllm_latency)} | "
            f"{result.xdp_rps / result.vllm_rps:.1f}x | "
            f"{latency_to_us(result.vllm_latency) / latency_to_us(result.xdp_latency):.1f}x |"
        )

    lines += [
        "",
        "## Routing-marker checks",
        "",
        "| Metric across the sweep | XDP | vLLM-SR |",
        "| --- | ---: | ---: |",
        f"| Aggregate route-distribution agreement | {percentage_range([item.xdp_marker_agreement for item in performance])} | {percentage_range([item.vllm_marker_agreement for item in performance])} |",
        f"| FIFO response-marker agreement | {percentage_range([item.xdp_fifo_agreement for item in performance])} | {percentage_range([item.vllm_fifo_agreement for item in performance])} |",
        "",
        "## Routing-correctness checks",
        "",
        "- 880 prompts in SPEED-Bench",
        "",
        "| Concurrency | XDP avg ms | XDP p99 ms | XDP RPS | vLLM-SR avg ms | vLLM-SR p99 ms | vLLM-SR RPS | XSR ↔ VSR routing agreement |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in correctness:
        lines.append(
            f"| {result.concurrency} | {result.xdp_avg:.3f} | {result.xdp_p99:.3f} | {result.xdp_rps:,.2f} | "
            f"{result.vllm_avg:.3f} | {result.vllm_p99:.3f} | {result.vllm_rps:,.2f} | "
            f"{result.agreement_percent:.2f}% ({result.agreement_count}/{result.agreement_total}) |"
        )

    performance_names = ", ".join(str(value) for value in PERFORMANCE_CONCURRENCIES)
    correctness_names = ", ".join(str(value) for value in CORRECTNESS_CONCURRENCIES)
    lines += [
        "",
        "## Raw reports",
        "",
        f"- Performance: `results/routing-performance/routing_performance_{{{performance_names}}}.md`",
        f"- Correctness: `results/routing-correctness/routing_correctness_benchmark_concurrency_{{{correctness_names}}}.md`",
        "",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines))


def latency_to_us(value: str) -> float:
    match = required_match(r"^([0-9.]+)(us|ms|s)$", value, "latency value")
    amount, unit = float(match.group(1)), match.group(2)
    return amount * {"us": 1, "ms": 1_000, "s": 1_000_000}[unit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_DIR / "wrk_benchmark.md")
    args = parser.parse_args()
    try:
        compile_report(args.results_dir, args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
