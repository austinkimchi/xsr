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
        "SIGNAL_PROFILE",
        "XSR_DISTILL_MODEL",
        "XSR_DISTILL_PARITY_DEBUG",
        "VSR_CONTAINER",
        "VSR_CONFIG_PATH",
        "VSR_CONFIG_SHA256",
        "VSR_SIGNAL_PROFILE",
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
    def test_intent_preflight_maps_qa_and_writing_prompts_to_fallback(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        function = source.split("preflight_routing_cases() {", 1)[1].split("\n}", 1)[0]
        intent_block = function.split('if [ "$SIGNAL_PROFILE" = intent ]; then', 1)[1].split("else", 1)[0]
        self.assertIn("others|answer this question: what is the capital of France?", intent_block)
        self.assertIn("others|write a short poem about rain", intent_block)
        self.assertNotIn("qa|answer this question", intent_block)
        self.assertNotIn("writing|write a short poem", intent_block)
        self.assertEqual(source.count("done < <(preflight_routing_cases)"), 3)

    def test_legacy_only_builds_generate_and_validate_the_requested_profile(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertGreaterEqual(
            source.count('if system_selected xsr || [ "$INCLUDE_XDP" = "1" ]; then'),
            2,
        )
        self.assertIn('KEYWORD_POLICY="$BUILD_KEYWORD_POLICY"', source)

    def test_metadata_uses_pre_generation_source_state(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('--source-working-tree "$XSR_SOURCE_WORKING_TREE"', source)
        self.assertLess(source.index("XSR_SOURCE_WORKING_TREE="), source.index("make -s KEYWORD_POLICY="))

    def test_xsr_warmup_uses_quiescence_without_a_router_restart(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("same-process-load-warmup", source)
        self.assertIn("wait_for_xsr_quiescence.py", source)
        self.assertNotIn("router-restart-after-load-warmup", source)
        self.assertNotIn("router-measurement.log", source)

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

    def test_intent_profile_selects_intent_adapter_and_reports_no_debug(self) -> None:
        output = dry_run(
            BENCHMARK_SYSTEMS="xsr,llmrouter", SIGNAL_PROFILE="intent",
            XSR_DISTILL_MODEL="/bin/true", PROMPTS_FILE="/data/intent.jsonl",
            WORKLOAD_ID="intent:heldout",
        )
        self.assertIn("effective_compiled_profile=intent", output)
        self.assertIn("parity_debug=0", output)
        self.assertIn("/benchmarks/llmrouter/configs/intent.yaml", output)

    def test_explicit_adapter_mismatch_fails(self) -> None:
        policy = SCRIPT.parents[2] / "config" / "policy_bm25.yaml"
        with self.assertRaises(subprocess.CalledProcessError):
            dry_run(
                BENCHMARK_SYSTEMS="llmrouter", SIGNAL_PROFILE="bm25",
                LLMROUTER_CONFIG=str(SCRIPT.parents[1] / "llmrouter/configs/ngram.yaml"),
                KEYWORD_POLICY=str(policy),
            )

    def test_explicit_workload_is_visible_in_dry_run(self) -> None:
        output = dry_run(PROMPTS_FILE="/data/intent.jsonl", WORKLOAD_ID="intent:heldout")
        self.assertIn("prompts_file=/data/intent.jsonl", output)
        self.assertIn("prompts_selection=explicit", output)
        self.assertIn("workload_id=intent:heldout", output)
        self.assertIn("xsr_warmup_lifecycle=same-process-load-warmup", output)
        self.assertIn("xsr_measured_instance_warmed=true", output)

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
