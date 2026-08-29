#!/usr/bin/env python3
"""HTTP reference path using the exact exported integer student semantics."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core import LABELS, integer_scores, predict, read_kernel_model


def content_from_request(body: dict) -> str:
    messages = body.get("messages", [])
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return message["content"]
    value = body.get("content")
    return value if isinstance(value, str) else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18082)
    args = parser.parse_args()
    model = read_kernel_model(args.model)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            prompt = content_from_request(json.loads(self.rfile.read(length)))
            intent = predict(integer_scores(prompt, model.weights, model.bias))
            payload = json.dumps({"category": LABELS[intent], "intent_id": intent}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args) -> None:
            return

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
