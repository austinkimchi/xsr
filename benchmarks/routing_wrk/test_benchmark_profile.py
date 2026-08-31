#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("benchmark.sh")


def dry_run(**overrides: str) -> str:
    env = os.environ.copy()
    for name in (
        "BENCHMARK_PROFILE",
        "BENCHMARK_SYSTEMS",
        "CONCURRENCY",
        "DURATION",
        "INCLUDE_STRESS",
        "KEYWORD_POLICY",
        "LLMROUTER_CONFIG",
        "TRIALS",
        "WARMUP_DURATION",
    ):
        env.pop(name, None)
    env.update({"BENCHMARK_DRY_RUN": "1", "PYTHON": sys.executable, "WRK_BIN": "/bin/true"})
    env.update(overrides)
    return subprocess.check_output([SCRIPT], env=env, text=True).strip()


class BenchmarkProfileTest(unittest.TestCase):
    def test_paper_profile_uses_shortened_main_sweep(self) -> None:
        output = dry_run(BENCHMARK_PROFILE="paper")
        self.assertIn("trials=5 duration=40s warmup_duration=3s", output)
        self.assertIn(r"concurrencies=1\ 2\ 4\ 8\ 16\ 32\ 64\ 96\ 128\ 192 ", output)
        self.assertNotIn(r"\ 256", output)
        self.assertIn("systems=direct,envoy-only,xsr,vsr,llmrouter", output)
        self.assertIn("llmrouter_config=", output)
        self.assertIn("/benchmarks/llmrouter/configs/ngram.yaml", output)

    def test_stress_option_restores_high_concurrency_points(self) -> None:
        output = dry_run(BENCHMARK_PROFILE="paper", INCLUDE_STRESS="1")
        self.assertIn(r"\ 192\ 256\ 512 ", output)
        self.assertIn("include_stress=1", output)

    def test_system_selector_is_reported(self) -> None:
        output = dry_run(BENCHMARK_SYSTEMS="xsr,vsr")
        self.assertIn("systems=xsr,vsr", output)
        self.assertIn("llmrouter_config=not-selected", output)

    def test_llmrouter_bm25_config_is_inferred_from_policy(self) -> None:
        policy = SCRIPT.parents[2] / "config" / "policy_bm25.yaml"
        output = dry_run(BENCHMARK_SYSTEMS="llmrouter", KEYWORD_POLICY=str(policy))
        self.assertIn("systems=llmrouter", output)
        self.assertIn("/benchmarks/llmrouter/configs/bm25.yaml", output)


if __name__ == "__main__":
    unittest.main()
