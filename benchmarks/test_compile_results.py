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


def route_section(
    heading: str,
    rps: str,
    avg_rps: str = "1.50k",
    p50: str = "800.00us",
    p95: str = "1.25ms",
    p99: str = "2.00ms",
) -> str:
    return f"""{heading}
```
    Latency     1.00ms
    Req/Sec     {avg_rps}    10.00     2.00k    70.00%
Requests/sec:   {rps}
[Lua] latency percentiles: p50={p50} p95={p95} p99={p99}
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
        self.assertEqual(result.route_avg_rps, 1500.0)
        self.assertEqual(result.route_p50_latency, "800.00us")
        self.assertEqual(result.route_p95_latency, "1.25ms")
        self.assertEqual(result.route_p99_latency, "2.00ms")

    def test_legacy_option_selects_only_legacy_xsr(self) -> None:
        result = self.parse_report(
            route_section("## [2/4] XSR (legacy) Route", "200.00")
            + route_section("## [3/4] XSR Route", "300.00"),
            "legacy",
        )

        self.assertEqual(result.route_label, "XSR (legacy)")
        self.assertEqual(result.route_rps, 200.0)

    def test_performance_parse_does_not_require_lua_route_checks(self) -> None:
        result = self.parse_report(
            route_section("## [3/4] XSR Route", "300.00")
        )

        self.assertEqual(result.route_rps, 300.0)

    def test_parses_scaled_average_request_rate(self) -> None:
        result = self.parse_report(
            route_section("## [3/4] XSR Route", "300.00", avg_rps="275.25")
        )

        self.assertEqual(result.route_avg_rps, 275.25)

    def test_compiled_report_includes_detailed_performance_summary(self) -> None:
        report = """# High-Performance wrk Benchmark Results

- Timestamp: `Sat Aug 22 10:17:16 PM PDT 2026`
- Connections: `1`
- Duration: `100s`

""" + route_section(
            "## [3/4] XSR Route", "300.00", "1.50k", "800.00us", "1.25ms", "2.00ms"
        ) + route_section(
            "## [4/4] vLLM-SR Route", "100.00", "275.25", "2.00ms", "3.00ms", "4.00ms"
        )
        original_performance = compiler.PERFORMANCE_CONCURRENCIES
        original_correctness = compiler.CORRECTNESS_CONCURRENCIES
        try:
            compiler.PERFORMANCE_CONCURRENCIES = (1,)
            compiler.CORRECTNESS_CONCURRENCIES = ()
            with tempfile.TemporaryDirectory() as directory:
                results = Path(directory)
                performance_dir = results / "routing-performance"
                performance_dir.mkdir()
                (performance_dir / "routing_performance_1.md").write_text(report)
                output = results / "wrk_benchmark.md"
                compiler.compile_report(results, output)
                rendered = output.read_text()
        finally:
            compiler.PERFORMANCE_CONCURRENCIES = original_performance
            compiler.CORRECTNESS_CONCURRENCIES = original_correctness

        self.assertIn("## Detailed performance summary", rendered)
        self.assertIn(
            "| 1 | 1.00 ms | 1,500.00 | 800.00 us | 1.25 ms | 2.00 ms | "
            "1.00 ms | 275.25 | 2.00 ms | 3.00 ms | 4.00 ms |",
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
