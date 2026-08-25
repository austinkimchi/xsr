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
    ("qa", 18394),
    ("writing", 18395),
)
PROMPTS = (
    ("coding", "Please debug this Python function and explain the code path."),
    ("math", "Solve this matrix equation and calculate the probability."),
    ("others", "Give a short friendly greeting about planning lunch."),
    ("qa", "Explain and answer this question about the capital of France."),
    ("writing", "Write a short draft essay about planning lunch."),
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
    response = subprocess.run(
        [
            "sudo",
            "ip",
            "netns",
            "exec",
            "ns1",
            "curl",
            "-fsS",
            "--max-time",
            "5",
            "-H",
            "Content-Type: application/json",
            "--data-binary",
            openai_body(prompt).decode(),
            "http://10.10.0.1:18081/v1/chat/completions",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return json.loads(response.stdout)["backend"]


def main() -> int:
    subprocess.run(["make", "dev"], cwd=ROOT, check=True)
    for process_name in ("sk_router", "xdp_router"):
        subprocess.run(
            ["sudo", "pkill", "-KILL", "-x", process_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    subprocess.run(["sudo", "ip", "netns", "exec", "ns1", "true"], cwd=ROOT, check=True)
    for port in (18081, 18391, 18392, 18393, 18394, 18395):
        subprocess.run(
            ["sudo", "iptables", "-I", "INPUT", "1", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
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

        with run_process(
            ["sudo", "env", "SK_ROUTER_MODE=sockmap", str(ROOT / "sk_router")]
        ) as router:
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
        for process_name in ("sk_router", "xdp_router"):
            subprocess.run(
                ["sudo", "pkill", "-KILL", "-x", process_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        for proc in backend_procs:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
