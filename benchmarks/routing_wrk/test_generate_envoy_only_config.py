#!/usr/bin/env python3
from __future__ import annotations

import unittest

from generate_envoy_only_config import ROUTES, config


class EnvoyOnlyConfigTest(unittest.TestCase):
    def test_router_only_config_has_all_marker_backends(self) -> None:
        rendered = config("172.18.0.1", {route: 18000 + index for index, route in enumerate(ROUTES)}, 8898)
        text = str(rendered)
        self.assertNotIn("ext_proc", text)
        self.assertEqual(len(rendered["static_resources"]["clusters"]), 5)
        self.assertEqual(len(rendered["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][0]["typed_config"]["http_filters"]), 1)


if __name__ == "__main__":
    unittest.main()
