#!/usr/bin/env python3
"""Regression coverage for prompt-export dataset argument forwarding."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).with_name("export_prompts.py")
SPEC = importlib.util.spec_from_file_location("routing_wrk_export_prompts", MODULE_PATH)
assert SPEC and SPEC.loader
export_prompts = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = export_prompts
SPEC.loader.exec_module(export_prompts)


class ExportPromptsDatasetTests(unittest.TestCase):
    def test_routerarena_split_default_and_override_reach_shared_loader(self) -> None:
        for extra_args, expected_split in (([], "full"), (["--routerarena-split", "sub_10"], "sub_10")):
            with self.subTest(expected_split=expected_split), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "prompts.jsonl"
                argv = [
                    str(MODULE_PATH),
                    "--dataset",
                    "routerarena",
                    "--output",
                    str(output),
                    *extra_args,
                ]
                with (
                    mock.patch.object(sys, "argv", argv),
                    mock.patch.object(export_prompts, "load_cases", return_value=([], {}, {})) as load_cases,
                    mock.patch.object(export_prompts, "load_policy", return_value={}),
                    mock.patch.object(export_prompts, "validate_policy", return_value=(False, [])),
                ):
                    export_prompts.main()

                bench_args = load_cases.call_args.args[0]
                self.assertEqual(bench_args.dataset, "routerarena")
                self.assertEqual(bench_args.routerarena_split, expected_split)


if __name__ == "__main__":
    unittest.main()
