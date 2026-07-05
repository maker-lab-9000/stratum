"""Controlled target site for the e2e stack (T24).

Serves a real page with configurable cache headers the pipeline samples: a MISS
edge state, an edge cache HIT via Server-Timing, no-cache Cache-Control, and an
Age that grows on every request — so the report's progression table reflects the
target's configured behaviour end to end. Any path is served (the fake LLM
treats a URL containing `__degrade__` as the degraded flow), so a single stack
drives happy + degraded.
"""

from __future__ import annotations

import itertools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_requests = itertools.count()

_BODY = (
    b"<!doctype html><html><head><title>Stratum e2e target</title></head>"
    b"<body><h1>ok</h1><p>controlled cache target</p></body></html>"
)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _serve(self, body: bytes) -> None:
        n = next(_requests)
        self.send_response(200)
        self.send_header("Server", "stratum-e2e-target")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Cache", "MISS")
        self.send_header("Server-Timing", "edge;desc=HIT")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Age", str(n * 5))  # grows across requests
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._serve(_BODY)

    def do_HEAD(self) -> None:
        self._serve(b"")

    def log_message(self, *args) -> None:  # quiet
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
