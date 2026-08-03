#!/usr/bin/env python3
"""Benchmark direct, direct-netns, XDP, vLLM SR, and userspace prompt routing paths."""

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
import select
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
DEFAULT_DATASET = "supralabs"
DEFAULT_DATASETS = (
    "supralabs",
    "empero-tasklist",
    "speed-bench",
    "routerbench",
    "synthetic-pld",
)
DEFAULT_LIMIT = 2000
DEFAULT_XDP_URL = "http://10.10.0.1:18081/v1/chat/completions"
HTTP_TIMEOUT_S = 10.0
FNV_OFFSET = 2166136261
FNV_PRIME = 16777619
NGRAM_FEATURES = 4096
NGRAM_MASK = NGRAM_FEATURES - 1
CLASSES = ("coding", "general", "math")
ROUTE_HEADERS = (
    "x-benchmark-route",
    "x-vllm-sr-route",
    "x-vsr-selected-decision",
    "x-vsr-selected-model",
    "x-selected-model",
)


@dataclasses.dataclass(frozen=True)
class DatasetSpec:
  name: str
  dataset_id: str
  config: str
  split: str
  loader: str
  description: str


@dataclasses.dataclass(frozen=True)
class PromptCase:
  prompt: str
  label: str
  source_index: int
  metadata: dict[str, Any]


@dataclasses.dataclass
class HttpResult:
  status: int
  elapsed_ms: float
  route: str | None
  error: str | None = None


DATASET_SPECS = {
    "supralabs": DatasetSpec(
        name="supralabs",
        dataset_id="SupraLabs/Prompt-Routing-Dataset",
        config="default",
        split="train",
        loader="dataset-server",
        description="Primary training/benchmark dataset with explicit prompt routing labels.",
    ),
    "empero-tasklist": DatasetSpec(
        name="empero-tasklist",
        dataset_id="empero-ai/tasklist-qwen3.5-9B-7500x-unfiltered",
        config="default",
        split="train",
        loader="dataset-server",
        description="Prompt task list with domain/subdomain/difficulty labels.",
    ),
    "speed-bench": DatasetSpec(
        name="speed-bench",
        dataset_id="nvidia/SPEED-Bench",
        config="qualitative",
        split="test",
        loader="dataset-server",
        description="Qualitative SPEED-Bench split with category-labeled prompts.",
    ),
    "routerbench": DatasetSpec(
        name="routerbench",
        dataset_id="withmartian/routerbench",
        config="0shot",
        split="pkl",
        loader="pickle",
        description="RouterBench 0-shot pickle with prompts from routing benchmarks.",
    ),
    "synthetic-pld": DatasetSpec(
        name="synthetic-pld",
        dataset_id="mayankthakur/synthetic-pld-benchmark",
        config="default",
        split="train",
        loader="dataset-server",
        description="Synthetic prompt-level domain benchmark with broad category labels.",
    ),
}


class MockHandler(http.server.BaseHTTPRequestHandler):
  server_version = "XdpBenchmarkMock/0.1"

  def do_POST(self) -> None:
    content_length = int(self.headers.get("content-length", "0"))
    body = self.rfile.read(content_length)
    self.server.requests.put(body)  # type: ignore[attr-defined]
    response = b'{"ok":true}\n'
    self.send_response(200)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(response)))
    self.send_header("Connection", "close")
    self.end_headers()
    self.wfile.write(response)

  def log_message(self, fmt: str, *args: object) -> None:
    if self.server.quiet:  # type: ignore[attr-defined]
      return
    super().log_message(fmt, *args)


class UserspaceProxyHandler(http.server.BaseHTTPRequestHandler):
  server_version = "XdpBenchmarkUserspaceProxy/0.1"

  def do_POST(self) -> None:
    content_length = int(self.headers.get("content-length", "0"))
    raw_body = self.rfile.read(content_length)

    try:
      payload = json.loads(raw_body)
    except json.JSONDecodeError:
      self.send_error(400, "request body must be JSON")
      return

    prompt = extract_prompt(payload)
    route, scores = route_prompt(self.server.model, prompt)  # type: ignore[attr-defined]
    status, headers, response = post_http(
        self.server.upstream_url,  # type: ignore[attr-defined]
        raw_body,
        route_header=False,
    )

    self.send_response(status)
    for key, value in headers.items():
      if key.lower() in {"connection", "transfer-encoding", "content-length"}:
        continue
      self.send_header(key, value)
    self.send_header("Content-Length", str(len(response)))
    self.send_header("X-Benchmark-Route", route)
    self.send_header("X-Benchmark-Scores", ",".join(str(score) for score in scores))
    self.end_headers()
    self.wfile.write(response)

  def log_message(self, fmt: str, *args: object) -> None:
    if self.server.quiet:  # type: ignore[attr-defined]
      return
    super().log_message(fmt, *args)


class ThreadingHTTPServer(http.server.ThreadingHTTPServer):
  allow_reuse_address = True
  daemon_threads = True
  request_queue_size = 4096


def truthy(value: Any) -> bool:
  if isinstance(value, bool):
    return value
  if isinstance(value, str):
    return value.strip().lower() in {"1", "true", "yes", "y"}
  return bool(value)


def normalize_label(row: dict[str, Any]) -> str:
  if truthy(row.get("coding_task")):
    return "coding"
  if truthy(row.get("math_task")):
    return "math"
  return "general"


def normalize_dataset_label(spec: DatasetSpec, row: dict[str, Any]) -> str | None:
  if spec.name == "supralabs":
    return normalize_label(row)
  if spec.name == "empero-tasklist":
    return normalize_domain_label(row.get("domain"), row.get("prompt", ""))
  if spec.name == "speed-bench":
    return normalize_category_label(row.get("category"))
  if spec.name == "routerbench":
    return normalize_routerbench_label(row)
  if spec.name == "synthetic-pld":
    return normalize_category_label(row.get("category"))
  raise ValueError(f"unknown dataset spec {spec.name!r}")


def normalize_domain_label(value: Any, prompt: Any = "") -> str | None:
  if not isinstance(value, str):
    return None
  domain = value.strip().lower().split("::", 1)[0]
  if domain == "coding":
    return "coding"
  if domain == "math":
    return "math"
  if domain == "cs":
    return "coding" if looks_like_coding_prompt(str(prompt)) else "general"
  if domain in {"creative", "conversation", "science"}:
    return "general"
  return None


def normalize_category_label(value: Any) -> str | None:
  if not isinstance(value, str):
    return None
  category = value.strip().lower()
  if category == "coding":
    return "coding"
  if category in {"math", "reasoning"}:
    return "math"
  if category in {
      "qa",
      "rag",
      "roleplay",
      "stem",
      "humanities",
      "writing",
      "summarization",
      "multilingual",
  }:
    return "general"
  return None


def normalize_routerbench_label(row: dict[str, Any]) -> str | None:
  name = str(
      row.get("eval_name")
      or row.get("benchmark")
      or row.get("dataset")
      or row.get("category")
      or row.get("source")
      or ""
  ).lower()
  prompt = str(row.get("prompt") or row.get("question") or "")
  if any(token in name for token in ("mbpp", "humaneval", "code", "programming")):
    return "coding"
  if any(token in name for token in ("gsm", "math", "mmlu")):
    return "math"
  if looks_like_coding_prompt(prompt):
    return "coding"
  if looks_like_math_prompt(prompt):
    return "math"
  return "general"


def looks_like_coding_prompt(prompt: str) -> bool:
  text = prompt.lower()
  needles = (
      "write a function",
      "write code",
      "implement",
      "debug",
      "python",
      "javascript",
      "typescript",
      "java ",
      "c++",
      "rust",
      "sql",
      "class ",
      "function ",
      "```",
  )
  return any(needle in text for needle in needles)


def looks_like_math_prompt(prompt: str) -> bool:
  text = prompt.lower()
  needles = (
      "solve",
      "equation",
      "calculate",
      "derivative",
      "integral",
      "prove",
      "probability",
      "geometry",
      "algebra",
      "integer",
      "number of",
  )
  return any(needle in text for needle in needles)


def row_prompt(row: dict[str, Any]) -> str:
  turns = row.get("turns")
  if isinstance(turns, list):
    parts = [turn.strip() for turn in turns if isinstance(turn, str) and turn.strip()]
    if parts:
      return "\n\n".join(parts)
  for key in ("prompt", "instruction", "question", "input"):
    value = row.get(key)
    if isinstance(value, str) and value.strip():
      return value.strip()
  raise ValueError(f"dataset row has no prompt-like field: {sorted(row)}")


def load_rows_with_datasets(spec: DatasetSpec, limit: int) -> list[dict[str, Any]]:
  from datasets import load_dataset  # type: ignore

  dataset = load_dataset(spec.dataset_id, spec.config, split=spec.split)
  rows = []
  for row in dataset:
    rows.append(dict(row))
    if len(rows) >= limit:
      break
  return rows


def dataset_server_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
  query = urllib.parse.urlencode(params)
  url = f"https://datasets-server.huggingface.co/{path}?{query}"
  with urllib.request.urlopen(url, timeout=60) as response:
    return json.load(response)


def load_rows_with_dataset_server(spec: DatasetSpec, limit: int) -> list[dict[str, Any]]:
  rows: list[dict[str, Any]] = []
  offset = 0
  page_size = min(100, max(1, limit))

  while len(rows) < limit:
    data = dataset_server_json(
        "rows",
        {
            "dataset": spec.dataset_id,
            "config": spec.config,
            "split": spec.split,
            "offset": offset,
            "length": page_size,
        },
    )
    page = [item["row"] for item in data.get("rows", [])]
    if not page:
      break
    rows.extend(page)
    offset += len(page)

  return rows[:limit]


def routerbench_cache_path(cache_dir: Path) -> Path:
  return cache_dir / "withmartian__routerbench-routerbench_0shot.pkl"


def load_rows_with_routerbench_pickle(cache_dir: Path, limit: int) -> list[dict[str, Any]]:
  try:
    import pandas as pd  # type: ignore
  except Exception as exc:
    raise RuntimeError("routerbench requires pandas to load Hugging Face pickle data") from exc

  cache_path = routerbench_cache_path(cache_dir)
  cache_path.parent.mkdir(parents=True, exist_ok=True)
  if not cache_path.exists():
    url = "https://huggingface.co/datasets/withmartian/routerbench/resolve/main/routerbench_0shot.pkl"
    with urllib.request.urlopen(url, timeout=300) as response, cache_path.open("wb") as file:
      shutil.copyfileobj(response, file)

  frame = pd.read_pickle(cache_path)
  rows: list[dict[str, Any]] = []
  for row in frame.head(limit).to_dict(orient="records"):
    rows.append({str(key): value for key, value in row.items()})
  return rows


def selected_dataset_specs(names: str) -> list[DatasetSpec]:
  specs: list[DatasetSpec] = []
  for name in (item.strip() for item in names.split(",") if item.strip()):
    if name == "all":
      specs.extend(DATASET_SPECS[item] for item in DEFAULT_DATASETS)
      continue
    try:
      specs.append(DATASET_SPECS[name])
    except KeyError as exc:
      choices = ", ".join(sorted([*DATASET_SPECS, "all"]))
      raise SystemExit(f"unknown dataset {name!r}; choose one of: {choices}") from exc
  return specs


def load_dataset_cases(
    limit: int, cache_dir: Path, fixture: Path | None, spec: DatasetSpec | None = None
) -> tuple[list[PromptCase], dict[str, Any]]:
  cache_dir.mkdir(parents=True, exist_ok=True)
  spec = spec or DATASET_SPECS[DEFAULT_DATASET]

  if fixture:
    with fixture.open() as file:
      rows = [json.loads(line) for line in file if line.strip()]
    dataset_meta = {
        "name": "fixture",
        "source": str(fixture),
        "loader": "fixture",
        "unique_rows": len(rows),
    }
  else:
    cache_path = cache_dir / f"{spec.dataset_id.replace('/', '__')}-{spec.config}-{spec.split}.jsonl"
    rows = []
    if cache_path.exists():
      with cache_path.open() as file:
        rows = [json.loads(line) for line in file if line.strip()]
      loader = "cache"
    if not rows:
      if spec.loader == "pickle":
        rows = load_rows_with_routerbench_pickle(cache_dir, limit)
        loader = "pickle"
      else:
        try:
          rows = load_rows_with_datasets(spec, limit)
          loader = "datasets"
        except Exception:
          rows = load_rows_with_dataset_server(spec, limit)
          loader = "dataset-server"
      with cache_path.open("w") as file:
        for row in rows:
          file.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    dataset_meta = {
        "name": spec.name,
        "source": spec.dataset_id,
        "config": spec.config,
        "split": spec.split,
        "loader": loader,
        "cache_path": str(cache_path),
        "unique_rows": len(rows),
        "description": spec.description,
    }

  if not rows:
    raise SystemExit("no dataset rows available")

  base_cases = []
  skipped_rows = 0
  for index, row in enumerate(rows):
    label = normalize_label(row) if fixture else normalize_dataset_label(spec, row)
    if not label:
      skipped_rows += 1
      continue
    try:
      prompt = row_prompt(row)
    except ValueError:
      skipped_rows += 1
      continue
    base_cases.append(
        PromptCase(
            prompt=prompt,
            label=label,
            source_index=index,
            metadata={
                "dataset": dataset_meta["name"],
                "category": row.get("category"),
                "domain": row.get("domain"),
                "subdomain": row.get("subdomain") or row.get("sub_category"),
                "difficulty": row.get("difficulty") or row.get("complexity_score"),
                "primary_domain": row.get("primary_domain"),
                "coding_task": row.get("coding_task"),
                "math_task": row.get("math_task"),
                "requires_reasoning": row.get("requires_reasoning"),
            },
        )
    )
  if not base_cases:
    raise SystemExit(f"no labeled prompt rows available for {dataset_meta['source']}")
  cases = [base_cases[index % len(base_cases)] for index in range(limit)]
  dataset_meta["usable_rows"] = len(base_cases)
  dataset_meta["skipped_rows"] = skipped_rows
  dataset_meta["requested_cases"] = limit
  dataset_meta["cycled_to_requested_cases"] = len(base_cases) < limit
  return cases, dataset_meta


def load_model(path: Path) -> dict[str, Any]:
  with path.open() as file:
    return json.load(file)


def hash3(c0: int, c1: int, c2: int) -> int:
  value = FNV_OFFSET
  for char in (c0, c1, c2):
    value ^= char
    value = (value * FNV_PRIME) & 0xFFFFFFFF
  return value & NGRAM_MASK


def route_prompt(model: dict[str, Any], prompt: str) -> tuple[str, list[int]]:
  scores = list(model["bias"])
  data = prompt.lower().encode("utf-8")

  for index in range(max(0, len(data) - 2)):
    feature = hash3(data[index], data[index + 1], data[index + 2])
    for class_id in range(3):
      scores[class_id] += model["weights"][class_id][feature]

  route_id = max(range(3), key=lambda class_id: scores[class_id])
  return model["classes"][route_id], scores


def extract_prompt(payload: dict[str, Any]) -> str:
  messages = payload.get("messages", [])
  if not isinstance(messages, list):
    return ""

  for message in reversed(messages):
    if not isinstance(message, dict) or message.get("role") != "user":
      continue
    content = message.get("content", "")
    if isinstance(content, str):
      return content
    if isinstance(content, list):
      return "\n".join(
          item.get("text", "")
          for item in content
          if isinstance(item, dict) and item.get("type") == "text"
      )
  return ""


def openai_chat_body(prompt: str) -> bytes:
  return json.dumps(
      {
          "model": "benchmark-model",
          "messages": [{"role": "user", "content": prompt}],
          "temperature": 0,
      },
      separators=(",", ":"),
  ).encode("utf-8")


def vllm_sr_eval_body(prompt: str) -> bytes:
  return json.dumps(
      {
          "messages": [{"role": "user", "content": prompt}],
          "evaluate_all_signals": True,
      },
      separators=(",", ":"),
  ).encode("utf-8")


def post_http(url: str, body: bytes, route_header: bool = True) -> tuple[int, dict[str, str], bytes]:
  parsed = urllib.parse.urlparse(url)
  connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=HTTP_TIMEOUT_S)
  path = parsed.path or "/"
  if parsed.query:
    path = f"{path}?{parsed.query}"
  try:
    connection.request(
        "POST",
        path,
        body=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    response = connection.getresponse()
    response_body = response.read()
    headers = {key: value for key, value in response.getheaders()}
    if route_header:
      headers = {key.lower(): value for key, value in headers.items()}
    return response.status, headers, response_body
  finally:
    connection.close()


def send_case(url: str, case: PromptCase) -> HttpResult:
  start = time.perf_counter_ns()
  try:
    status, headers, _ = post_http(url, openai_chat_body(case.prompt))
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    route = route_from_headers(headers)
    return HttpResult(status=status, elapsed_ms=elapsed_ms, route=route)
  except Exception as exc:
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    return HttpResult(status=0, elapsed_ms=elapsed_ms, route=None, error=str(exc))


def send_vllm_sr_eval_case(url: str, case: PromptCase) -> HttpResult:
  start = time.perf_counter_ns()
  try:
    status, _, response_body = post_http(url, vllm_sr_eval_body(case.prompt), route_header=False)
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    route = None
    if status < 400:
      route = route_from_vllm_sr_eval(json.loads(response_body))
    return HttpResult(status=status, elapsed_ms=elapsed_ms, route=route)
  except Exception as exc:
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    return HttpResult(status=0, elapsed_ms=elapsed_ms, route=None, error=str(exc))


def route_from_headers(headers: dict[str, str]) -> str | None:
  for header in ROUTE_HEADERS:
    route = canonical_route(headers.get(header))
    if route:
      return route
  return None


def route_from_vllm_sr_eval(payload: dict[str, Any]) -> str | None:
  decision_result = payload.get("decision_result")
  if not isinstance(decision_result, dict):
    decision_result = {}

  for value in (
      decision_result.get("decision_name"),
      payload.get("routing_decision"),
  ):
    route = canonical_route(value if isinstance(value, str) else None)
    if route:
      return route

  recommended_models = payload.get("recommended_models")
  if isinstance(recommended_models, list):
    for value in recommended_models:
      route = canonical_route(value if isinstance(value, str) else None)
      if route:
        return route

  for group_name in ("matched_signals", "used_signals"):
    signals = decision_result.get(group_name)
    if not isinstance(signals, dict):
      continue
    domains = signals.get("domains") or signals.get("domain")
    if not isinstance(domains, list):
      continue
    for value in domains:
      route = canonical_vllm_sr_domain(value if isinstance(value, str) else None)
      if route:
        return route

  confidences = payload.get("signal_confidences")
  if isinstance(confidences, dict):
    for key in confidences:
      if isinstance(key, str) and key.startswith("domain:"):
        route = canonical_vllm_sr_domain(key.split(":", 1)[1])
        if route:
          return route

  return None


def canonical_vllm_sr_domain(value: str | None) -> str | None:
  if not value:
    return None
  normalized = value.strip().lower().replace("_", " ")
  if "computer science" in normalized or "coding" in normalized or "code" in normalized:
    return "coding"
  if "math" in normalized or "reasoning" in normalized:
    return "math"
  return "general"


def canonical_route(value: str | None) -> str | None:
  if not value:
    return None
  normalized = value.strip().lower().replace("_", "-")
  for suffix in ("-route", "-model"):
    if normalized.endswith(suffix):
      normalized = normalized[: -len(suffix)]
  if normalized in CLASSES:
    return normalized
  if "coding" in normalized or "code" in normalized:
    return "coding"
  if "math" in normalized or "reasoning" in normalized:
    return "math"
  if "general" in normalized:
    return "general"
  return None


def run_client_worker(url: str) -> int:
  for line in sys.stdin:
    try:
      item = json.loads(line)
      result = send_case(url, PromptCase(item["prompt"], item.get("label", ""), 0, {}))
      print(json.dumps(dataclasses.asdict(result), separators=(",", ":")), flush=True)
    except Exception as exc:
      print(
          json.dumps(
              {"status": 0, "elapsed_ms": 0.0, "route": None, "error": str(exc)},
              separators=(",", ":"),
          ),
          flush=True,
      )
  return 0


def run_batch_client_worker(args: argparse.Namespace) -> int:
  with args.worker_cases.open() as file:
    cases = [
        PromptCase(
            prompt=item["prompt"],
            label=item.get("label", ""),
            source_index=item.get("source_index", 0),
            metadata=item.get("metadata", {}),
        )
        for item in (json.loads(line) for line in file if line.strip())
    ]

  result = run_http_mode(
      "xdp-worker", cases, args.client_worker_batch, args.concurrency, False
  )
  print(json.dumps(result, separators=(",", ":")), flush=True)
  return 0


def read_cpu_totals() -> tuple[int, int]:
  with Path("/proc/stat").open() as file:
    fields = file.readline().split()[1:]
  values = [int(value) for value in fields]
  idle = values[3] + values[4]
  return sum(values), idle


def cpu_percent(start: tuple[int, int], end: tuple[int, int]) -> float:
  total_delta = end[0] - start[0]
  idle_delta = end[1] - start[1]
  if total_delta <= 0:
    return 0.0
  return 100.0 * (total_delta - idle_delta) / total_delta


def percentile(values: list[float], pct: float) -> float | None:
  if not values:
    return None
  ordered = sorted(values)
  index = int(round((pct / 100.0) * (len(ordered) - 1)))
  return ordered[index]


def summarize_http_results(
    mode: str,
    cases: list[PromptCase],
    results: list[HttpResult],
    elapsed_s: float,
    cpu: float,
    accuracy_available: bool,
) -> dict[str, Any]:
  latencies = [result.elapsed_ms for result in results if not result.error and result.status]
  correct = 0
  classified = 0
  if accuracy_available:
    for case, result in zip(cases, results):
      if result.route:
        classified += 1
        if result.route == case.label:
          correct += 1
  accuracy = None
  if accuracy_available and cases and classified:
    accuracy = correct / len(cases)

  return {
      "mode": mode,
      "status": "ok",
      "requests": len(results),
      "errors": sum(1 for result in results if result.error or result.status >= 400 or result.status == 0),
      "accuracy": accuracy,
      "classified": classified if accuracy_available else None,
      "correct": correct if accuracy_available else None,
      "latency_ms": {
          "p50": percentile(latencies, 50),
          "p95": percentile(latencies, 95),
          "p99": percentile(latencies, 99),
          "max": max(latencies) if latencies else None,
      },
      "slow_requests": {
          "gt_100ms": sum(1 for latency in latencies if latency > 100),
          "gt_1000ms": sum(1 for latency in latencies if latency > 1000),
      },
      "requests_per_second": len(results) / elapsed_s if elapsed_s > 0 else 0.0,
      "cpu_utilization_percent": cpu,
  }


def apply_routes_to_summary(
    summary: dict[str, Any], cases: list[PromptCase], routes: list[str]
) -> dict[str, Any]:
  correct = sum(1 for case, route in zip(cases, routes) if route == case.label)
  summary["accuracy"] = (correct / len(cases)) if cases else None
  summary["classified"] = len(routes)
  summary["correct"] = correct
  if len(routes) < len(cases):
    summary["missing_route_events"] = len(cases) - len(routes)
  return summary


@contextlib.contextmanager
def run_server(handler: type[http.server.BaseHTTPRequestHandler], host: str, port: int, **attrs: Any):
  server = ThreadingHTTPServer((host, port), handler)
  server.requests = queue.Queue()
  server.quiet = attrs.pop("quiet", True)
  for key, value in attrs.items():
    setattr(server, key, value)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  try:
    yield server
  finally:
    server.shutdown()
    server.server_close()


def run_http_mode(
    mode: str,
    cases: list[PromptCase],
    url: str,
    concurrency: int,
    accuracy_available: bool,
) -> dict[str, Any]:
  cpu_start = read_cpu_totals()
  start = time.perf_counter()
  if concurrency <= 1:
    results = [send_case(url, case) for case in cases]
  else:
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
      results = list(executor.map(lambda case: send_case(url, case), cases))
  elapsed_s = time.perf_counter() - start
  cpu_end = read_cpu_totals()
  return summarize_http_results(
      mode, cases, results, elapsed_s, cpu_percent(cpu_start, cpu_end), accuracy_available
  )


def run_vllm_sr_eval_http_mode(
    cases: list[PromptCase],
    url: str,
    concurrency: int,
) -> dict[str, Any]:
  cpu_start = read_cpu_totals()
  start = time.perf_counter()
  if concurrency <= 1:
    results = [send_vllm_sr_eval_case(url, case) for case in cases]
  else:
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
      results = list(executor.map(lambda case: send_vllm_sr_eval_case(url, case), cases))
  elapsed_s = time.perf_counter() - start
  cpu_end = read_cpu_totals()
  return summarize_http_results(
      "vllm-sr", cases, results, elapsed_s, cpu_percent(cpu_start, cpu_end), True
  )


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


def read_router_output(router: subprocess.Popen[str], output: queue.Queue[str]) -> None:
  if not router.stdout:
    return
  for line in router.stdout:
    output.put(line.rstrip())


def wait_for_route_event(output: queue.Queue[str], timeout_s: float) -> str | None:
  deadline = time.time() + timeout_s
  while time.time() < deadline:
    try:
      line = output.get(timeout=0.2)
    except queue.Empty:
      continue
    if not line.startswith("{"):
      continue
    try:
      event = json.loads(line)
    except json.JSONDecodeError:
      continue
    if event.get("event") == "route":
      return event.get("domain")
  return None


def drain_route_events(output: queue.Queue[str], wanted: int, timeout_s: float) -> list[str]:
  routes: list[str] = []
  deadline = time.time() + timeout_s
  while len(routes) < wanted and time.time() < deadline:
    route = wait_for_route_event(output, max(0.1, deadline - time.time()))
    if route is None:
      break
    routes.append(route)
  return routes


def read_worker_result(client: subprocess.Popen[str], timeout_s: float) -> HttpResult | None:
  if not client.stdout:
    return None
  ready, _, _ = select.select([client.stdout], [], [], timeout_s)
  if not ready:
    return None
  line = client.stdout.readline()
  if not line:
    return None
  return HttpResult(**json.loads(line))


def write_worker_cases(path: Path, cases: list[PromptCase]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("w") as file:
    for case in cases:
      file.write(
          json.dumps(
              {
                  "prompt": case.prompt,
                  "label": case.label,
                  "source_index": case.source_index,
                  "metadata": case.metadata,
              },
              separators=(",", ":"),
          )
          + "\n"
      )


def add_input_allow_rule(ifname: str, port: int) -> None:
  subprocess.run(
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
      ],
      check=True,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
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
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
  )


def add_port_allow_rule(port: int) -> None:
  subprocess.run(
      ["iptables", "-I", "INPUT", "1", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"],
      check=True,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
  )


def remove_port_allow_rule(port: int) -> None:
  subprocess.run(
      ["iptables", "-D", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"],
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
  )


def run_netns_batch_mode(
    mode: str, args: argparse.Namespace, cases: list[PromptCase], url: str
) -> dict[str, Any]:
  if os.geteuid() != 0:
    return skipped(mode, "network namespace benchmark requires root")
  if not shutil.which("ip"):
    return skipped(mode, "iproute2 is required")

  try:
    subprocess.run(
        ["ip", "netns", "exec", args.xdp_netns, "true"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
  except subprocess.CalledProcessError:
    return skipped(mode, f"missing network namespace {args.xdp_netns!r}")

  worker_cases_path = args.report_dir / f".{mode}_worker_cases.jsonl"
  firewall_rule_added = False
  try:
    write_worker_cases(worker_cases_path, cases)
    if args.manage_firewall:
      add_input_allow_rule(args.xdp_ifname, args.mock_port)
      firewall_rule_added = True

    cpu_start = read_cpu_totals()
    start = time.perf_counter()
    batch = subprocess.run(
        [
            "ip",
            "netns",
            "exec",
            args.xdp_netns,
            sys.executable,
            "-u",
            str(ROOT / "scripts" / "benchmark_routing.py"),
            "--http-timeout",
            str(args.http_timeout),
            "--concurrency",
            str(args.concurrency),
            "--worker-cases",
            str(worker_cases_path),
            "--client-worker-batch",
            url,
        ],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=batch_worker_timeout(args, len(cases)),
    )
    elapsed_s = time.perf_counter() - start
    cpu_end = read_cpu_totals()

    if batch.returncode != 0:
      return skipped(mode, f"netns batch worker failed: {batch.stderr.strip()}")

    summary = json.loads(batch.stdout.strip().splitlines()[-1])
    summary["mode"] = mode
    summary["cpu_utilization_percent"] = cpu_percent(cpu_start, cpu_end)
    summary["batch_wall_elapsed_s"] = elapsed_s
    summary["batch_wall_requests_per_second"] = len(cases) / elapsed_s if elapsed_s > 0 else 0.0
    return summary
  finally:
    if firewall_rule_added:
      remove_input_allow_rule(args.xdp_ifname, args.mock_port)
    with contextlib.suppress(FileNotFoundError):
      worker_cases_path.unlink()


def run_xdp_mode(args: argparse.Namespace, cases: list[PromptCase]) -> dict[str, Any]:
  if os.geteuid() != 0:
    return skipped("xdp", "XDP benchmark requires root")
  if not shutil.which("ip"):
    return skipped("xdp", "iproute2 is required")

  for command in (["ip", "link", "show", "dev", args.xdp_ifname], ["ip", "netns", "exec", args.xdp_netns, "true"]):
    try:
      subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
      return skipped("xdp", f"missing XDP interface/netns prerequisite: {' '.join(command)}")

  subprocess.run(["make", "dev"], cwd=ROOT, check=True)
  subprocess.run(["ip", "link", "set", "dev", args.xdp_ifname, "xdp", "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

  router: subprocess.Popen[str] | None = None
  client: subprocess.Popen[str] | None = None
  output: queue.Queue[str] = queue.Queue()
  firewall_rule_added = False
  worker_cases_path = args.report_dir / ".xdp_worker_cases.jsonl"

  try:
    write_worker_cases(worker_cases_path, cases)

    if args.manage_firewall:
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
      return skipped("xdp", "xdp_router did not attach")

    client = subprocess.Popen(
        [
            "ip",
            "netns",
            "exec",
            args.xdp_netns,
            sys.executable,
            "-u",
            str(ROOT / "scripts" / "benchmark_routing.py"),
            "--http-timeout",
            str(args.http_timeout),
            "--client-worker",
            args.xdp_url,
        ],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    results: list[HttpResult] = []
    accuracy_cases = cases[: min(args.xdp_accuracy_limit, len(cases))]
    probe_failures = 0
    for case in accuracy_cases:
      if not client.stdin or not client.stdout:
        return skipped("xdp", "failed to start netns client worker")
      client.stdin.write(json.dumps({"prompt": case.prompt, "label": case.label}) + "\n")
      client.stdin.flush()
      result = read_worker_result(client, args.http_timeout + 1.0)
      if result is None:
        return skipped("xdp", "netns client worker did not return an HTTP result")
      if result.error or result.status == 0:
        probe_failures += 1
        if probe_failures >= 3:
          return skipped(
              "xdp",
              f"netns client worker failed {probe_failures} XDP probe requests; "
              f"check --xdp-url ({args.xdp_url}) and --mock-port ({args.mock_port})",
          )
      results.append(result)

    routes = drain_route_events(output, len(results), args.xdp_event_timeout)

    cpu_start = read_cpu_totals()
    start = time.perf_counter()
    batch = subprocess.run(
        [
            "ip",
            "netns",
            "exec",
            args.xdp_netns,
            sys.executable,
            "-u",
            str(ROOT / "scripts" / "benchmark_routing.py"),
            "--http-timeout",
            str(args.http_timeout),
            "--concurrency",
            str(args.concurrency),
            "--worker-cases",
            str(worker_cases_path),
            "--client-worker-batch",
            args.xdp_url,
        ],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=batch_worker_timeout(args, len(cases)),
    )
    elapsed_s = time.perf_counter() - start
    cpu_end = read_cpu_totals()

    if batch.returncode != 0:
      return skipped("xdp", f"netns batch worker failed: {batch.stderr.strip()}")

    summary = json.loads(batch.stdout.strip().splitlines()[-1])
    summary["mode"] = "xdp"
    summary["cpu_utilization_percent"] = cpu_percent(cpu_start, cpu_end)
    summary["batch_wall_elapsed_s"] = elapsed_s
    summary["batch_wall_requests_per_second"] = len(cases) / elapsed_s if elapsed_s > 0 else 0.0
    summary["accuracy_sample_size"] = len(accuracy_cases)
    return apply_routes_to_summary(summary, accuracy_cases, routes)
  finally:
    if client:
      if client.stdin:
        client.stdin.close()
      try:
        client.wait(timeout=5)
      except subprocess.TimeoutExpired:
        client.kill()
        client.wait(timeout=5)
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
    subprocess.run(["ip", "link", "set", "dev", args.xdp_ifname, "xdp", "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with contextlib.suppress(FileNotFoundError):
      worker_cases_path.unlink()


def batch_worker_timeout(args: argparse.Namespace, case_count: int) -> float:
  workers = max(1, args.concurrency)
  waves = (case_count + workers - 1) // workers
  return max(args.http_timeout + 30, waves * (args.http_timeout + 1.0) + 10)


def skipped(mode: str, reason: str) -> dict[str, Any]:
  return {"mode": mode, "status": "skipped", "reason": reason}


def socket_open(host: str, port: int, timeout_s: float = 0.5) -> bool:
  try:
    with socket.create_connection((host, port), timeout=timeout_s):
      return True
  except OSError:
    return False


def find_executable(name: str) -> str | None:
  found = shutil.which(name)
  if found:
    return found

  sudo_user = os.environ.get("SUDO_USER")
  candidates = []
  if sudo_user:
    candidates.append(Path("/home") / sudo_user / ".local" / "bin" / name)
  candidates.append(Path.home() / ".local" / "bin" / name)

  for candidate in candidates:
    if candidate.exists() and os.access(candidate, os.X_OK):
      return str(candidate)
  return None


def run_vllm_sr_mode(args: argparse.Namespace, cases: list[PromptCase]) -> dict[str, Any]:
  if args.vllm_sr_eval_url:
    url = normalize_vllm_sr_eval_url(args.vllm_sr_eval_url)
    runner = lambda: run_vllm_sr_eval_http_mode(cases, url, args.concurrency)
  else:
    if args.vllm_sr_url:
      url = normalize_vllm_sr_chat_url(args.vllm_sr_url)
    else:
      if not find_executable("vllm-sr"):
        return skipped("vllm-sr", "vllm-sr CLI is not installed")
      port = next((candidate for candidate in (8180, 8080) if socket_open("127.0.0.1", candidate)), None)
      if port is None:
        return skipped("vllm-sr", "no running vLLM SR chat endpoint; pass --vllm-sr-url")
      url = f"http://127.0.0.1:{port}/v1/chat/completions"
    runner = lambda: run_http_mode("vllm-sr", cases, url, args.concurrency, True)
  firewall_rule_added = False
  try:
    if args.manage_firewall and os.geteuid() == 0:
      add_port_allow_rule(args.mock_port)
      firewall_rule_added = True
    return runner()
  finally:
    if firewall_rule_added:
      remove_port_allow_rule(args.mock_port)


def normalize_vllm_sr_chat_url(value: str) -> str:
  url = value.strip().rstrip("/")
  if url.endswith("/v1/chat/completions"):
    return url
  if url.endswith("/v1"):
    return f"{url}/chat/completions"
  return f"{url}/v1/chat/completions"


def normalize_vllm_sr_eval_url(value: str) -> str:
  url = value.strip().rstrip("/")
  if url.endswith("/api/v1/eval"):
    return url
  if url.endswith("/api/v1"):
    return f"{url}/eval"
  return f"{url}/api/v1/eval"


def write_reports(report: dict[str, Any], report_dir: Path) -> None:
  report_dir.mkdir(parents=True, exist_ok=True)
  json_path = report_dir / "xdp_routing_benchmark.json"
  md_path = report_dir / "xdp_routing_benchmark.md"

  with json_path.open("w") as file:
    json.dump(legacy_report_view(report), file, indent=2, sort_keys=True)
    file.write("\n")

  lines = [
      "# XDP Routing Benchmark",
      "",
      f"- Command: `{' '.join(report['command'])}`",
      f"- Kernel: {report['machine']['kernel']}",
      f"- CPU count: {report['machine']['cpu_count']}",
  ]
  lines.extend(format_control_section(report))

  for dataset_report in report["datasets"]:
    dataset = dataset_report["dataset"]
    lines.extend(
        [
            "",
            f"## Dataset: {dataset['source']}",
            "",
            f"- Dataset key: `{dataset.get('name', 'unknown')}`",
            f"- Config/split: `{dataset.get('config', 'n/a')}` / `{dataset.get('split', 'n/a')}`",
            f"- Requested cases: {dataset['requested_cases']}",
            f"- Unique rows: {dataset['unique_rows']}",
            f"- Usable labeled rows: {dataset.get('usable_rows', dataset['unique_rows'])}",
            f"- Skipped rows: {dataset.get('skipped_rows', 0)}",
            f"- Loader: {dataset['loader']}",
            "",
            "| Mode | Status | Accuracy | p50 ms | p95 ms | p99 ms | max ms | >1s | RPS | CPU % |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for result in dataset_report["results"]:
      lines.append(format_result_row(result))
      if result["status"] == "skipped":
        lines.append(f"\nSkipped `{result['mode']}`: {result['reason']}\n")

  with md_path.open("w") as file:
    file.write("\n".join(lines) + "\n")


def format_control_section(report: dict[str, Any]) -> list[str]:
  rows = []
  for dataset_report in report["datasets"]:
    control = select_control_result(dataset_report["results"])
    if not control:
      continue
    dataset = dataset_report["dataset"]
    rows.append(format_control_row(dataset.get("name", "unknown"), control))

  if not rows:
    return []

  return [
      "",
      "## Control Result",
      "",
      "Preferred control is `direct-netns` when available, otherwise `direct`.",
      "",
      "| Dataset | Mode | Status | Accuracy | p99 ms | max ms | >1s | RPS | CPU % |",
      "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
      *rows,
  ]


def select_control_result(results: list[dict[str, Any]]) -> dict[str, Any] | None:
  by_mode = {result.get("mode"): result for result in results}
  for mode in ("direct-netns", "direct"):
    result = by_mode.get(mode)
    if result and result.get("status") == "ok":
      return result
  for mode in ("direct-netns", "direct"):
    result = by_mode.get(mode)
    if result:
      return result
  return None


def format_control_row(dataset_name: str, result: dict[str, Any]) -> str:
  latency = result.get("latency_ms") or {}
  accuracy = result.get("accuracy")
  return (
      "| {dataset} | {mode} | {status} | {accuracy} | {p99} | {max_latency} | {gt_1000ms} | {rps} | {cpu} |".format(
          dataset=dataset_name,
          mode=result["mode"],
          status=result["status"],
          accuracy="n/a" if accuracy is None else f"{accuracy:.4f}",
          p99=format_metric(latency.get("p99")),
          max_latency=format_metric(latency.get("max")),
          gt_1000ms=format_count((result.get("slow_requests") or {}).get("gt_1000ms")),
          rps=format_metric(result.get("requests_per_second")),
          cpu=format_metric(result.get("cpu_utilization_percent")),
      )
  )


def legacy_report_view(report: dict[str, Any]) -> dict[str, Any]:
  if len(report["datasets"]) != 1:
    return report
  dataset_report = report["datasets"][0]
  legacy = dict(report)
  legacy["dataset"] = dataset_report["dataset"]
  legacy["results"] = dataset_report["results"]
  return legacy


def format_result_row(result: dict[str, Any]) -> str:
  latency = result.get("latency_ms") or {}
  accuracy = result.get("accuracy")
  return (
      "| {mode} | {status} | {accuracy} | {p50} | {p95} | {p99} | {max_latency} | {gt_1000ms} | {rps} | {cpu} |".format(
          mode=result["mode"],
          status=result["status"],
          accuracy="n/a" if accuracy is None else f"{accuracy:.4f}",
          p50=format_metric(latency.get("p50")),
          p95=format_metric(latency.get("p95")),
          p99=format_metric(latency.get("p99")),
          max_latency=format_metric(latency.get("max")),
          gt_1000ms=format_count((result.get("slow_requests") or {}).get("gt_1000ms")),
          rps=format_metric(result.get("requests_per_second")),
          cpu=format_metric(result.get("cpu_utilization_percent")),
        )
  )


def format_count(value: Any) -> str:
  if value is None:
    return "n/a"
  return str(int(value))


def format_metric(value: Any) -> str:
  if value is None:
    return "n/a"
  return f"{float(value):.3f}"


def run_modes_for_cases(
    args: argparse.Namespace,
    cases: list[PromptCase],
    modes: list[str],
    model: dict[str, Any],
    mock_url: str,
    proxy_url: str,
) -> list[dict[str, Any]]:
  results = []
  for mode in modes:
    if mode == "direct":
      results.append(run_http_mode("direct", cases, mock_url, args.concurrency, False))
    elif mode == "direct-netns":
      results.append(run_netns_batch_mode("direct-netns", args, cases, args.xdp_url))
    elif mode == "userspace":
      with run_server(
          UserspaceProxyHandler,
          args.proxy_host,
          args.proxy_port,
          model=model,
          upstream_url=mock_url,
          quiet=True,
      ):
        results.append(run_http_mode("userspace", cases, proxy_url, args.concurrency, True))
    elif mode == "xdp":
      results.append(run_xdp_mode(args, cases))
    elif mode == "vllm-sr":
      results.append(run_vllm_sr_mode(args, cases))
    else:
      results.append(skipped(mode, "unknown mode"))
  return results


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--client-worker")
  parser.add_argument("--client-worker-batch")
  parser.add_argument("--worker-cases", type=Path)
  parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
  parser.add_argument("--concurrency", type=int, default=16)
  parser.add_argument("--http-timeout", type=float, default=10.0)
  parser.add_argument("--modes", default="direct,direct-netns,xdp,vllm-sr,userspace")
  parser.add_argument("--dataset", default=DEFAULT_DATASET, help="single dataset key to benchmark")
  parser.add_argument(
      "--datasets",
      help="comma-separated dataset keys, or 'all'; overrides --dataset",
  )
  parser.add_argument("--fixture-jsonl", type=Path)
  parser.add_argument("--cache-dir", type=Path, default=Path.home() / ".cache" / "xdp-routing-proof")
  parser.add_argument("--report-dir", type=Path, default=ROOT / "reports")
  parser.add_argument("--mock-host", default="0.0.0.0")
  parser.add_argument("--mock-port", type=int, default=18081)
  parser.add_argument("--proxy-host", default="127.0.0.1")
  parser.add_argument("--proxy-port", type=int, default=18082)
  parser.add_argument("--model-path", type=Path, default=ROOT / "models" / "xdp_ngram_model_fnv.json")
  parser.add_argument("--xdp-ifname", default="veth0")
  parser.add_argument("--xdp-netns", default="ns1")
  parser.add_argument("--xdp-url", default=DEFAULT_XDP_URL)
  parser.add_argument("--xdp-event-timeout", type=float, default=10.0)
  parser.add_argument("--xdp-accuracy-limit", type=int, default=200)
  parser.add_argument("--manage-firewall", action=argparse.BooleanOptionalAction, default=True)
  parser.add_argument(
      "--vllm-sr-url",
      help="vLLM SR OpenAI-compatible chat endpoint base URL or /v1/chat/completions URL",
  )
  parser.add_argument(
      "--vllm-sr-eval-url",
      help="legacy vLLM SR /api/v1/eval endpoint; use only for eval-mode comparison",
  )
  args = parser.parse_args()
  if "--xdp-url" not in sys.argv and args.mock_port != 18081:
    parsed = urllib.parse.urlparse(args.xdp_url)
    netloc = f"{parsed.hostname}:{args.mock_port}"
    args.xdp_url = urllib.parse.urlunparse(
        parsed._replace(netloc=netloc)
    )
  return args


def main() -> int:
  args = parse_args()
  global HTTP_TIMEOUT_S
  HTTP_TIMEOUT_S = args.http_timeout
  if args.client_worker:
    return run_client_worker(args.client_worker)
  if args.client_worker_batch:
    return run_batch_client_worker(args)

  modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
  model = load_model(args.model_path)
  specs = (
      [DATASET_SPECS[DEFAULT_DATASET]]
      if args.fixture_jsonl
      else selected_dataset_specs(args.datasets or args.dataset)
  )
  mock_client_host = "127.0.0.1" if args.mock_host == "0.0.0.0" else args.mock_host
  mock_url = f"http://{mock_client_host}:{args.mock_port}/v1/chat/completions"
  proxy_url = f"http://{args.proxy_host}:{args.proxy_port}/v1/chat/completions"
  dataset_reports = []

  with run_server(MockHandler, args.mock_host, args.mock_port, quiet=True):
    for spec in specs:
      cases, dataset_meta = load_dataset_cases(
          args.limit,
          args.cache_dir,
          args.fixture_jsonl,
          spec,
      )
      results = run_modes_for_cases(args, cases, modes, model, mock_url, proxy_url)
      dataset_reports.append({"dataset": dataset_meta, "results": results})

  report = {
      "command": sys.argv,
      "machine": {
          "platform": platform.platform(),
          "kernel": platform.release(),
          "python": platform.python_version(),
          "cpu_count": os.cpu_count(),
      },
      "datasets": dataset_reports,
  }
  write_reports(report, args.report_dir)
  print(json.dumps(legacy_report_view(report), indent=2, sort_keys=True))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
