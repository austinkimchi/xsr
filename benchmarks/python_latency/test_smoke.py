from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from aiohttp import web

from benchmarks.python_latency.client import benchmark


def test_local_keepalive_smoke(tmp_path: Path) -> None:
    async def run() -> None:
        async def handler(request: web.Request) -> web.Response:
            await request.read()
            return web.json_response({"backend": "mock"})

        app = web.Application()
        app.router.add_post("/v1/chat/completions", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        prompts = tmp_path / "prompts.jsonl"
        prompts.write_text(json.dumps({"model": "MoM", "messages": []}) + "\n", encoding="utf-8")
        args = argparse.Namespace(
            url=f"http://127.0.0.1:{port}/v1/chat/completions",
            rate=20.0,
            connections=2,
            duration=0.2,
            warmup=0.1,
            timeout=2.0,
            prompts=prompts,
            system="mock",
            trial=1,
            output_dir=tmp_path,
            connection_audit=False,
        )
        try:
            results, details = await benchmark(args)
        finally:
            await runner.cleanup()
        assert len(results) == 4
        assert all(row.http_status == 200 and row.backend_marker == "mock" for row in results)
        assert [row.worker_id for row in results] == [0, 1, 0, 1]
        assert sum(row["connections_created"] for row in details["connection_stats_including_warmup"]) == 2
        assert sum(row["connections_reused"] for row in details["connection_stats_including_warmup"]) == 4

    asyncio.run(run())

