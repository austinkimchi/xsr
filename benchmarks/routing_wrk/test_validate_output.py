#!/usr/bin/env python3
from __future__ import annotations

import unittest

from validate_output import invalid_reasons


NORMAL = """10 requests in 1.00s, 1KB read\nRequests/sec: 10.00\n"""


class ValidateOutputTest(unittest.TestCase):
    def test_normal_output_is_valid(self) -> None:
        self.assertEqual(invalid_reasons(NORMAL), [])

    def test_transport_errors_are_invalid(self) -> None:
        reasons = invalid_reasons(NORMAL + "Socket errors: connect 1, read 2, write 3, timeout 4\n")
        self.assertEqual(reasons, ["connect errors=1", "read errors=2", "write errors=3", "timeout errors=4"])

    def test_non_success_http_responses_are_invalid(self) -> None:
        self.assertEqual(invalid_reasons(NORMAL + "Non-2xx or 3xx responses: 5\n"), ["non-2xx/3xx responses=5"])

    def test_zero_or_missing_request_count_is_invalid(self) -> None:
        self.assertEqual(invalid_reasons("0 requests in 1.00s\n"), ["zero completed requests"])
        self.assertEqual(invalid_reasons("no summary\n"), ["completed-request count was not reported"])

    def test_fewer_completions_than_connections_is_invalid(self) -> None:
        output = """4 threads and 256 connections
17 requests in 45.06s, 1.88KB read
Requests/sec: 0.38
"""
        self.assertEqual(
            invalid_reasons(output),
            ["completed requests=17 below connection count=256"],
        )

    def test_at_least_one_completion_per_connection_is_valid(self) -> None:
        output = """4 threads and 256 connections
256 requests in 45.00s, 28KB read
Requests/sec: 5.69
"""
        self.assertEqual(invalid_reasons(output), [])


if __name__ == "__main__":
    unittest.main()
