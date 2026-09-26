from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from benchmarks.llmrouter import validate_full_prompt_correctness as validation


class ProvenanceGuardTest(unittest.TestCase):
    def test_rejects_tracked_implementation_changes(self) -> None:
        with mock.patch.object(
            validation.subprocess,
            "check_output",
            side_effect=[" M benchmarks/llmrouter/serve_benchmark.py\n"],
        ):
            with self.assertRaisesRegex(RuntimeError, "serve_benchmark.py"):
                validation.require_reproducible_source_tree(
                    validation.ROOT / "results" / "correctness"
                )

    def test_allows_tracked_changes_inside_output_directory(self) -> None:
        output = validation.ROOT / "results" / "correctness"
        with mock.patch.object(
            validation.subprocess,
            "check_output",
            side_effect=[" M results/correctness/ngram.json\n", "abc123\n"],
        ):
            self.assertEqual(validation.require_reproducible_source_tree(output), "abc123")

    def test_ignores_untracked_paths_because_git_status_excludes_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self.assertEqual(
                validation.disallowed_tracked_changes(output, ""),
                [],
            )
