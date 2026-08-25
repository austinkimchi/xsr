#!/usr/bin/env python3
"""Tests for choosing one XSR route variant in compiled reports."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("compile_results.py")
SPEC = importlib.util.spec_from_file_location("compile_results", MODULE_PATH)
assert SPEC and SPEC.loader
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def route_section(heading: str, rps: str) -> str:
    return f"""{heading}
```
    Latency     1.00ms
Requests/sec:   {rps}
[Lua] aggregate route agreement: 0.900000 (90/100); fifo_matches=80 fifo_mismatches=20
```
"""


class CompileResultsTests(unittest.TestCase):
    def parse_report(self, sections: str, route: str = "auto") -> object:
        report = """# High-Performance wrk Benchmark Results

- Timestamp: `Sat Aug 22 10:17:16 PM PDT 2026`
- Connections: `1`
- Duration: `100s`

""" + sections + route_section("## [4/4] vLLM-SR Route", "100.00")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.md"
            path.write_text(report)
            return compiler.parse_performance(path, route)

    def test_auto_prefers_sockmap_when_both_routes_are_present(self) -> None:
        result = self.parse_report(
            route_section("## [2/4] XSR (legacy) Route", "200.00")
            + route_section("## [3/4] XSR Route", "300.00")
        )

        self.assertEqual(result.route_label, "XSR (SOCKMAP)")
        self.assertEqual(result.route_rps, 300.0)

    def test_legacy_option_selects_only_legacy_xsr(self) -> None:
        result = self.parse_report(
            route_section("## [2/4] XSR (legacy) Route", "200.00")
            + route_section("## [3/4] XSR Route", "300.00"),
            "legacy",
        )

        self.assertEqual(result.route_label, "XSR (legacy)")
        self.assertEqual(result.route_rps, 200.0)


if __name__ == "__main__":
    unittest.main()
