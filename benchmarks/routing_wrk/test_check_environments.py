#!/usr/bin/env python3
"""Regression tests for system-selective benchmark preflight checks."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("check_environments.sh")


class EnvironmentCheckTest(unittest.TestCase):
    def run_check(self, systems: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "calls.log"

            def executable(name: str, body: str) -> Path:
                path = root / name
                path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
                path.chmod(0o755)
                return path

            benchmark_python = executable("benchmark-python", "exit 0")
            llmrouter_python = executable("llmrouter-python", "exit 0")
            llmrouter_bin = executable("llmrouter", "exit 0")
            for name in ("cc", "curl", "ip", "iptables", "ethtool"):
                executable(name, "exit 0")
            executable("make", f"echo make >> '{log}'; exit 0")
            executable(
                "docker",
                f"echo docker >> '{log}'; "
                "if [ \"$1\" = inspect ]; then echo true; fi; exit 0",
            )

            env = os.environ.copy()
            env.update({
                "PATH": f"{root}:/usr/bin:/bin",
                "BENCHMARK_SYSTEMS": systems,
                "BENCHMARK_PYTHON": str(benchmark_python),
                "LLMROUTER_PYTHON": str(llmrouter_python),
                "LLMROUTER_BIN": str(llmrouter_bin),
            })
            subprocess.run([SCRIPT], env=env, check=True, capture_output=True, text=True)
            return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def test_direct_does_not_probe_optional_environments(self) -> None:
        self.assertEqual(self.run_check("direct"), [])

    def test_xsr_only_runs_the_bpf_check(self) -> None:
        self.assertEqual(self.run_check("direct,xsr"), ["make"])

    def test_vsr_only_probes_docker(self) -> None:
        self.assertEqual(self.run_check("vsr"), ["docker", "docker"])

    def test_llmrouter_does_not_probe_bpf_or_docker(self) -> None:
        self.assertEqual(self.run_check("llmrouter"), [])


if __name__ == "__main__":
    unittest.main()
