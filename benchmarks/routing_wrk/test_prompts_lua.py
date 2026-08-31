#!/usr/bin/env python3
"""Lightweight checks for load-time prompt annotation normalization."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prompts.lua")


class PromptsLuaTest(unittest.TestCase):
    def test_annotation_normalization_is_outside_timed_request(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        request_body = source.split("request = function()", 1)[1].split("done = function", 1)[0]
        self.assertNotIn("gsub", request_body)
        self.assertLess(source.index("gsub"), source.index("request = function()"))
        self.assertIn('os.getenv("PROMPTS_FILE")', source)

    @unittest.skipUnless(shutil.which("lua"), "lua interpreter is unavailable")
    def test_annotation_is_not_sent_and_other_payload_bytes_are_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prompts = Path(directory) / "prompts.jsonl"
            expected = '{"model":"MoM","messages":[{"role":"user","content":"unchanged"}]}'
            prompts.write_text(expected[:-1] + ',"x_expected_route":"coding"}\n', encoding="utf-8")
            harness = Path(directory) / "harness.lua"
            harness.write_text(
                "wrk = {headers = {}, format = function(method, path, headers, body) return body end}\n"
                f"dofile({str(SCRIPT)!r})\n"
                "io.write(request())\n",
                encoding="utf-8",
            )
            env = {**os.environ, "PROMPTS_FILE": str(prompts)}
            output = subprocess.check_output(["lua", harness], env=env, text=True)
            self.assertEqual(output, expected)


if __name__ == "__main__":
    unittest.main()
