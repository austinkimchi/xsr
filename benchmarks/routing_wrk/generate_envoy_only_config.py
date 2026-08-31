#!/usr/bin/env python3
"""Generate the benchmark's router-only Envoy baseline configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROUTES = ("coding", "math", "qa", "writing", "others")


def config(gateway: str, ports: dict[str, int], port: int) -> dict[str, object]:
    routes = [
        {
            "match": {"prefix": "/", "headers": [{"name": "x-benchmark-backend", "string_match": {"exact": route}}]},
            "route": {"cluster": f"{route}_cluster", "timeout": "30s"},
        }
        for route in ROUTES
    ]
    routes.append({"match": {"prefix": "/"}, "route": {"cluster": "coding_cluster", "timeout": "30s"}})
    clusters = [
        {
            "name": f"{route}_cluster",
            "connect_timeout": "5s",
            "type": "STATIC",
            "lb_policy": "ROUND_ROBIN",
            "load_assignment": {
                "cluster_name": f"{route}_cluster",
                "endpoints": [{"lb_endpoints": [{"endpoint": {"address": {"socket_address": {"address": gateway, "port_value": ports[route]}}}}]}],
            },
        }
        for route in ROUTES
    ]
    return {
        "static_resources": {
            "listeners": [{
                "name": "http",
                "address": {"socket_address": {"address": "0.0.0.0", "port_value": port}},
                "filter_chains": [{"filters": [{"name": "envoy.filters.network.http_connection_manager", "typed_config": {
                    "@type": "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
                    "stat_prefix": "benchmark_envoy_only",
                    "route_config": {"name": "routes", "virtual_hosts": [{"name": "all", "domains": ["*"], "routes": routes}]},
                    # Deliberately router-only: never add ExtProc here.
                    "http_filters": [{"name": "envoy.filters.http.router", "typed_config": {"@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"}}],
                }}]}],
            }],
            "clusters": clusters,
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", required=True)
    parser.add_argument("--port", type=int, default=8898)
    parser.add_argument("--coding-port", type=int, required=True)
    parser.add_argument("--math-port", type=int, required=True)
    parser.add_argument("--qa-port", type=int, required=True)
    parser.add_argument("--writing-port", type=int, required=True)
    parser.add_argument("--others-port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ports = {route: getattr(args, f"{route}_port") for route in ROUTES}
    args.output.write_text(json.dumps(config(args.gateway, ports, args.port), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
