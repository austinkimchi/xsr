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
        "BENCHMARK_MODE",
        "BENCHMARK_SYSTEMS",
        "CONCURRENCY",
        "DURATION",
        "INCLUDE_STRESS",
        "KEYWORD_POLICY",
        "LLMROUTER_CONFIG",
        "PROMPTS_EXPLICIT",
        "PROMPTS_FILE",
        "RANDOM_SEED",
        "RATES",
        "TRIALS",
        "WARMUP_DURATION",
        "WORKLOAD_ID",
        "WRK2_BIN",
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

    def test_explicit_workload_is_visible_in_dry_run(self) -> None:
        output = dry_run(PROMPTS_FILE="/data/intent.jsonl", WORKLOAD_ID="intent:heldout")
        self.assertIn("prompts_file=/data/intent.jsonl", output)
        self.assertIn("prompts_selection=explicit", output)
        self.assertIn("workload_id=intent:heldout", output)
        self.assertIn("xsr_measured_instance_warmed=false", output)

    def test_paper_fixed_rate_dry_run_uses_reviewed_slice(self) -> None:
        output = dry_run(
            BENCHMARK_PROFILE="paper", BENCHMARK_MODE="fixed-rate",
            CONCURRENCY="64", WRK2_BIN="/bin/true",
        )
        self.assertIn("mode=fixed-rate", output)
        self.assertIn(r"rates=100\ 250\ 500\ 750\ 900", output)
        self.assertIn("random_seed=20260826", output)
        self.assertIn("concurrencies=64", output)


if __name__ == "__main__":
    unittest.main()
