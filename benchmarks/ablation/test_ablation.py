from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from run import ci95, write_native_workload


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "build" / "ablation" / "native_benchmark"


class AblationHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "ablation-native-build"], cwd=ROOT, check=True,
                       stdout=subprocess.DEVNULL)

    def test_workload_uses_last_user_message_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "prompts.jsonl"
            binary = Path(directory) / "prompts.bin"
            source.write_text(json.dumps({"messages": [
                {"role": "user", "content": "old"},
                {"role": "assistant", "content": "reply"},
                {"role": "user", "content": "calculate derivative"},
            ]}) + "\n", encoding="utf-8")
            self.assertEqual(write_native_workload(source, binary), 1)
            result = subprocess.run([str(NATIVE), "verify-routing", "bm25", str(binary)],
                                    text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)["mismatches"], 0)

    def test_routing_realizations_agree_on_representative_inputs(self) -> None:
        records = [
            {"messages": [{"role": "user", "content": "implement a function"}]},
            {"messages": [{"role": "user", "content": "solve the derivative"}]},
            {"messages": [{"role": "user", "content": "tell a story"}]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "prompts.jsonl"
            binary = Path(directory) / "prompts.bin"
            source.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
            write_native_workload(source, binary)
            for signal in ("ngram", "bm25"):
                result = subprocess.run([str(NATIVE), "verify-routing", signal, str(binary)],
                                        text=True, capture_output=True, check=True)
                self.assertEqual(json.loads(result.stdout)["inputs"], 3)

    def test_bm25_hash_collision_is_an_unknown_token(self) -> None:
        records = [
            {"messages": [{"role": "user", "content": "code"}]},
            {"messages": [{"role": "user", "content": "zsydrxi"}]},
            {"messages": [{"role": "user", "content": "unknown-token"}]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "prompts.jsonl"
            binary = Path(directory) / "prompts.bin"
            source.write_text(
                "".join(json.dumps(row) + "\n" for row in records), encoding="utf-8"
            )
            write_native_workload(source, binary)
            result = subprocess.run(
                [str(NATIVE), "verify-routing", "bm25", str(binary)],
                text=True,
                capture_output=True,
                check=True,
            )
            routed = subprocess.run(
                [str(NATIVE), "dump-routing", "bm25", "xsr", str(binary)],
                text=True,
                capture_output=True,
                check=True,
            )
        self.assertEqual(json.loads(result.stdout), {
            "check": "routing-equivalence",
            "signal": "bm25",
            "inputs": 3,
            "mismatches": 0,
        })
        self.assertEqual(json.loads(routed.stdout)["signal_masks"], [1, 0, 0])

    def test_policy_realizations_agree_for_complete_signal_domain(self) -> None:
        result = subprocess.run([str(NATIVE), "verify-policy"], text=True,
                                capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {
            "check": "policy-equivalence", "signal_states": 32, "mismatches": 0,
        })

    def test_five_trial_ci_uses_students_t(self) -> None:
        mean, stdev, half_width = ci95([1, 2, 3, 4, 5])
        self.assertEqual(mean, 3)
        self.assertAlmostEqual(half_width, 2.776 * stdev / (5 ** 0.5))

    def test_forwarding_build_has_explicit_bypass(self) -> None:
        source = (ROOT / "bpf" / "programs" / "sk_router.bpf.c").read_text(encoding="utf-8")
        self.assertIn("#ifdef XSR_FORWARDING_ONLY", source)
        self.assertIn("route = SK_ROUTE_CODING", source)
        self.assertIn("return skb->len", source)


if __name__ == "__main__":
    unittest.main()
