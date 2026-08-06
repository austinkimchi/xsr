#!/usr/bin/env python3
"""Verify SK_SKB routing by checking backend-specific response markers."""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = (
    ("coding", 18391),
    ("math", 18392),
    ("others", 18393),
)
PROMPTS = (
    ("coding", "Please debug this Python function and explain the code path."),
    ("math", "Solve this matrix equation and calculate the probability."),
    ("others", "Write a short friendly paragraph about planning lunch."),
)


@contextlib.contextmanager
def run_process(args: list[str]):
    proc = subprocess.Popen(
        args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        yield proc
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=2)
        except Exception:
            proc.kill()


def wait_for_port(
    port: int, timeout_s: float = 5.0, proc: subprocess.Popen[str] | None = None
) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=1)
            raise RuntimeError(
                f"process exited before port {port} opened\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
            conn.connect()
            conn.close()
            return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"port {port} did not open")


def openai_body(prompt: str) -> bytes:
    return json.dumps(
        {
            "model": "smoke",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        separators=(",", ":"),
    ).encode()


def send_prompt(prompt: str) -> str:
    conn = http.client.HTTPConnection("127.0.0.1", 18081, timeout=5)
    conn.request(
        "POST",
        "/v1/chat/completions",
        body=openai_body(prompt),
        headers={"Content-Type": "application/json", "Connection": "close"},
    )
    response = conn.getresponse()
    body = response.read()
    conn.close()
    if response.status != 200:
        raise AssertionError(f"unexpected status {response.status}: {body!r}")
    return json.loads(body)["backend"]


def main() -> int:
    subprocess.run(["make", "dev"], cwd=ROOT, check=True)
    backend_procs = []
    try:
        for backend, port in BACKENDS:
            proc = subprocess.Popen(
                [str(ROOT / "benchmarks" / "mock_backend"), str(port), backend],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            backend_procs.append(proc)
            wait_for_port(port)

        with run_process([str(ROOT / "sk_router")]) as router:
            wait_for_port(18081, proc=router)
            results = []
            for expected, prompt in PROMPTS:
                actual = send_prompt(prompt)
                results.append({"expected": expected, "actual": actual})
                if actual != expected:
                    raise AssertionError(results)

            print(json.dumps({"ok": True, "results": results}, separators=(",", ":")))
            return 0
    finally:
        for proc in backend_procs:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
