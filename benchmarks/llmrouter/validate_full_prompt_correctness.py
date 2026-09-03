#!/usr/bin/env python3
"""Correctness-only XSR versus LLMRouter validation for deterministic signals."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from benchmarks.llmrouter.xsr_router import configured_method  # noqa: E402
from benchmarks.routing_correctness import benchmark  # noqa: E402


LLMROUTER_REVISION = "da3430baaea672743c3957457b0c76faba19876e"
XSR_SOURCE = "46864cac7479552735f564dc49880d00d8b54b14"
BACKENDS = (
    (benchmark.DEFAULT_VLLM_CODING_BACKEND_PORT, "coding"),
    (benchmark.DEFAULT_VLLM_MATH_BACKEND_PORT, "math"),
    (benchmark.DEFAULT_VLLM_OTHERS_BACKEND_PORT, "others"),
    (benchmark.DEFAULT_VLLM_QA_BACKEND_PORT, "qa"),
    (benchmark.DEFAULT_VLLM_WRITING_BACKEND_PORT, "writing"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def installed_llmrouter_revision() -> str:
    command = [
        str(ROOT / ".venv-llmrouter" / "bin" / "python"),
        "-c",
        "import json; from importlib.metadata import distribution; "
        "print(json.loads(distribution('llmrouter-lib').read_text('direct_url.json'))"
        "['vcs_info']['commit_id'])",
    ]
    return subprocess.check_output(command, cwd=ROOT, text=True).strip()


def routing_args(config: Path) -> argparse.Namespace:
    return argparse.Namespace(
        config=config,
        dataset="combined",
        routerarena_split="full",
        per_route=None,
        cache_dir=benchmark.DEFAULT_CACHE_DIR,
        concurrency=1,
        timeout_s=10.0,
        event_timeout_s=10.0,
        xdp_url=benchmark.DEFAULT_XDP_URL,
        xdp_ifname="veth0",
        xdp_netns="ns1",
        xdp_backend_port=18081,
        vllm_sr_url=benchmark.DEFAULT_VLLM_SR_URL,
        vllm_backend_port=benchmark.DEFAULT_VLLM_CODING_BACKEND_PORT,
        vllm_math_backend_port=benchmark.DEFAULT_VLLM_MATH_BACKEND_PORT,
        vllm_others_backend_port=benchmark.DEFAULT_VLLM_OTHERS_BACKEND_PORT,
        vllm_qa_backend_port=benchmark.DEFAULT_VLLM_QA_BACKEND_PORT,
        vllm_writing_backend_port=benchmark.DEFAULT_VLLM_WRITING_BACKEND_PORT,
        setup=False,
        no_build=True,
        no_firewall=False,
        no_mock_backends=False,
    )


def clear_persistent_connection() -> None:
    connection = getattr(benchmark._thread_local, "conn", None)
    if connection is not None:
        with contextlib.suppress(Exception):
            connection.close()
        delattr(benchmark._thread_local, "conn")


def llmrouter_route_from_response(headers: dict[str, str], body: bytes) -> str | None:
    """Read OpenClaw's end-to-end selection from its OpenAI `model` field."""
    route = benchmark.route_from_headers(headers)
    if route:
        return route
    with contextlib.suppress(json.JSONDecodeError, UnicodeDecodeError):
        payload = json.loads(body)
        if isinstance(payload, dict):
            return benchmark.canonical_route(payload.get("model"))
    return None


def wait_for_llmrouter(process: subprocess.Popen[bytes], url: str) -> None:
    deadline = time.monotonic() + 30
    health_url = url.rstrip("/") + "/health"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"LLMRouter exited during startup with status {process.returncode}")
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("LLMRouter did not become healthy within 30 seconds")


@contextlib.contextmanager
def llmrouter_server(router_config: Path, port: int):
    python = ROOT / ".venv-llmrouter" / "bin" / "python"
    command = [
        str(python),
        str(ROOT / "benchmarks" / "llmrouter" / "serve_benchmark.py"),
        "--config",
        str(ROOT / "benchmarks" / "llmrouter" / "configs" / "serve-local.yaml"),
        "--router",
        "xsr_reference",
        "--router-config",
        str(router_config),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    environment = {
        **os.environ,
        "LLMROUTER_PLUGINS": str(ROOT / "benchmarks" / "llmrouter" / "custom_routers"),
    }
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_llmrouter(process, f"http://127.0.0.1:{port}")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def compact_result(observation: dict[str, Any]) -> dict[str, Any]:
    prompt = observation["prompt"]
    return {
        "case_id": observation["case_id"],
        "source": observation["source"],
        "source_index": observation["source_index"],
        "prompt_length": len(prompt),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "reference_route": observation["expected_route"],
        "matched_keyword": observation.get("matched_keyword"),
        "route": observation.get("route"),
        "status": observation.get("status"),
        "error": observation.get("error"),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    sources = summary["per_source"]
    lines = [
        f"# LLMRouter Full-Prompt {report['method'].upper()} Correctness",
        "",
        f"- Concurrency: `{report['concurrency']}`",
        f"- Corpus: `{summary['total']}` requests",
        f"- XSR↔LLMRouter agreement: `{summary['agreement_count']}/{summary['total']}` "
        f"(`{summary['agreement_percent']:.3f}%`)",
        f"- Reference three-way agreement: `{summary['three_way_agreement_count']}/{summary['total']}`",
        f"- Mismatches: `{summary['mismatch_count']}`",
        "",
        "## Corpus breakdown",
        "",
        "| Source | Agreement |",
        "| --- | ---: |",
    ]
    for source, values in sorted(sources.items()):
        lines.append(
            f"| {source} | {values['agreement_count']}/{values['total']} "
            f"({values['agreement_percent']:.3f}%) |"
        )
    lines += [
        "",
        "Every row in the JSON artifact records the case identity, source index, prompt length/hash, "
        "reference route, XSR route, and end-to-end LLMRouter-selected backend.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=("ngram",), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--llmrouter-port", type=int, default=18083)
    args = parser.parse_args()

    if os.geteuid() != 0:
        os.execvp("sudo", ["sudo", sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])

    config = (ROOT / "config" / f"policy_{args.method}.yaml").resolve()
    router_config = (ROOT / "benchmarks" / "llmrouter" / "configs" / f"{args.method}.yaml").resolve()
    if configured_method(router_config) != args.method:
        raise RuntimeError("LLMRouter adapter method does not match requested method")
    revision = installed_llmrouter_revision()
    if revision != LLMROUTER_REVISION:
        raise RuntimeError(f"installed LLMRouter revision {revision} != pinned {LLMROUTER_REVISION}")

    subprocess.run(["make", f"KEYWORD_POLICY={config}", "policy"], cwd=ROOT, check=True)
    subprocess.run(["make", f"KEYWORD_POLICY={config}", "dev"], cwd=ROOT, check=True)

    run_args = routing_args(config)
    cases, dataset, _ = benchmark.load_cases(run_args)
    if len(cases) != benchmark.SPEED_BENCH_ROWS + benchmark.ROUTERARENA_ROWS["full"]:
        raise RuntimeError(f"expected 9,280 full-corpus cases, loaded {len(cases)}")

    benchmark.sanitize_benchmark_processes()
    with contextlib.ExitStack() as stack:
        for port, backend_name in BACKENDS:
            stack.enter_context(benchmark.mock_backend(port, backend_name))
        xsr = benchmark.run_sockmap(run_args, cases)
        if xsr.get("status") != "ok":
            raise RuntimeError(f"XSR correctness run did not complete: {xsr.get('reason', xsr)}")

        clear_persistent_connection()
        with llmrouter_server(router_config, args.llmrouter_port) as url:
            original_response_parser = benchmark.route_from_response
            benchmark.route_from_response = llmrouter_route_from_response
            try:
                start = time.perf_counter()
                llm_results = benchmark.send_cases_concurrently(url, cases, 10.0, 1)
                wall_seconds = time.perf_counter() - start
            finally:
                benchmark.route_from_response = original_response_parser
        clear_persistent_connection()

    llm = benchmark.summarize("llmrouter", llm_results, wall_seconds, None, None, len(cases))
    if llm["errors"] or llm["route_counts"]["unknown"]:
        raise RuntimeError(
            f"LLMRouter run incomplete: errors={llm['errors']}, "
            f"unknown_routes={llm['route_counts']['unknown']}"
        )

    xsr_by_id = {item["case_id"]: compact_result(item) for item in xsr["results"]}
    llm_by_id = {item["case_id"]: compact_result(item) for item in llm["results"]}
    if set(xsr_by_id) != set(llm_by_id):
        raise RuntimeError("XSR and LLMRouter result identities differ")

    rows: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    per_source: dict[str, dict[str, int | float]] = {}
    three_way = 0
    for case_id in sorted(xsr_by_id):
        xsr_item = xsr_by_id[case_id]
        llm_item = llm_by_id[case_id]
        routes_match = xsr_item["route"] == llm_item["route"]
        three_way_match = routes_match and xsr_item["route"] == xsr_item["reference_route"]
        row = {
            **xsr_item,
            "xsr_route": xsr_item.pop("route"),
            "llmrouter_route": llm_item["route"],
            "routes_match": routes_match,
            "three_way_match": three_way_match,
        }
        rows.append(row)
        bucket = per_source.setdefault(row["source"], {"total": 0, "agreement_count": 0})
        bucket["total"] = int(bucket["total"]) + 1
        bucket["agreement_count"] = int(bucket["agreement_count"]) + int(routes_match)
        three_way += int(three_way_match)
        if not routes_match:
            mismatches.append(
                {
                    "case_id": row["case_id"],
                    "prompt_length": row["prompt_length"],
                    "xsr_route": row["xsr_route"],
                    "llmrouter_route": row["llmrouter_route"],
                    "reference_route": row["reference_route"],
                    "relevant_matched_keyword_or_score": row["matched_keyword"],
                    "likely_cause": "requires individual investigation",
                }
            )
    for values in per_source.values():
        values["agreement_percent"] = 100.0 * int(values["agreement_count"]) / int(values["total"])

    agreement = len(rows) - len(mismatches)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "xsr-llmrouter-full-prompt-correctness-v1",
        "method": args.method,
        "concurrency": 1,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provenance": {
            "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "xsr_source": XSR_SOURCE,
            "llmrouter_revision": revision,
            "policy_path": str(config.relative_to(ROOT)),
            "policy_sha256": sha256(config),
            "router_config_path": str(router_config.relative_to(ROOT)),
            "router_config_sha256": sha256(router_config),
            "platform": platform.platform(),
            "kernel": platform.release(),
        },
        "dataset": dataset,
        "summary": {
            "total": len(rows),
            "agreement_count": agreement,
            "agreement_percent": 100.0 * agreement / len(rows),
            "three_way_agreement_count": three_way,
            "mismatch_count": len(mismatches),
            "per_source": per_source,
        },
        "results": rows,
    }
    json_path = output_dir / f"{args.method}_full_corpus.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(output_dir / f"{args.method}_report.md", report)
    if mismatches:
        (output_dir / f"{args.method}_mismatches.json").write_text(
            json.dumps(mismatches, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
