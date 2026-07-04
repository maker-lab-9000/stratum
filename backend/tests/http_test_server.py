"""A minimal raw HTTP/1.1 test server for sampler/integration tests.

Handling the wire bytes directly (rather than via a framework) is deliberate:
it lets tests assert on exact header case, header order, and duplicate headers
(e.g. two `Via`) — the very things the sampler must preserve verbatim (T04).

One request per connection, then the socket closes (`Connection: close`), so
each sample is a fresh connection. A ``responder(count, request)`` callback
decides each response and may ``await asyncio.sleep(...)`` to simulate slow
responses / timeouts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

# responder(request_count, parsed_request) -> raw response bytes
Responder = Callable[[int, dict], Awaitable[bytes]]


def parse_request(data: bytes) -> dict:
    text = data.decode("latin-1")
    lines = text.split("\r\n")
    method, path, version = lines[0].split(" ", 2)
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line:
            continue
        key, _, value = line.partition(":")
        headers.append((key.strip(), value.strip()))
    return {"method": method, "path": path, "version": version, "headers": headers}


def build_response(
    status: int,
    reason: str,
    headers: list[tuple[str, str]],
    body: bytes = b"",
) -> bytes:
    """Assemble raw response bytes with exact header order/case as given."""
    head = f"HTTP/1.1 {status} {reason}\r\n"
    for key, value in headers:
        head += f"{key}: {value}\r\n"
    head += f"Content-Length: {len(body)}\r\n"
    head += "Connection: close\r\n\r\n"
    return head.encode("latin-1") + body


class RawHTTPServer:
    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self._server: asyncio.AbstractServer | None = None
        self.count = 0
        self.received: list[dict] = []

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError:
            writer.close()
            return
        request = parse_request(data)
        self.count += 1
        self.received.append(request)
        response = await self._responder(self.count, request)
        writer.write(response)
        await writer.drain()
        writer.close()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


def received_header(request: dict, name: str) -> str | None:
    """Case-insensitive lookup of a header the server received."""
    for key, value in request["headers"]:
        if key.lower() == name.lower():
            return value
    return None
