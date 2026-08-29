#!/usr/bin/env python3
"""HTTP reference path using the exact exported integer student semantics."""

from __future__ import annotations

import argparse
import http.client
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
    parser.add_argument("--proxy", action="store_true", help="forward to the existing mock backend after classification")
    args = parser.parse_args()
    model = read_kernel_model(args.model)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self) -> None:
            super().setup()
            self.backend_connections: dict[int, http.client.HTTPConnection] = {}

        def finish(self) -> None:
            for connection in self.backend_connections.values():
                connection.close()
            super().finish()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            request_body = self.rfile.read(length)
            prompt = content_from_request(json.loads(request_body))
            intent = predict(integer_scores(prompt, model.weights, model.bias))
            if args.proxy:
                backend_port = 18391 if intent == 3 else 18392 if intent == 9 else 18393
                connection = self.backend_connections.setdefault(
                    backend_port, http.client.HTTPConnection("127.0.0.1", backend_port, timeout=30)
                )
                connection.request("POST", self.path, request_body, {
                    "Content-Type": "application/json", "Connection": "keep-alive"
                })
                response = connection.getresponse()
                payload = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("X-XSR-Intent", LABELS[intent])
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            payload = json.dumps({"category": LABELS[intent], "intent_id": intent}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format: str, *args) -> None:
            return

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
