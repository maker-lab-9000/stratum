"""Per-job progress event bus (spec §3 — one event per stage).

The orchestrator emits stage events through ``JobBus.emit``; T10's SSE endpoint
subscribes. History is buffered so a late subscriber gets current state first,
then live events (documented replay policy). A ``terminal`` event ends a stream.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import AsyncIterator


class JobBus:
    def __init__(self) -> None:
        self._history: list[dict] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._seq = itertools.count()
        self.closed = False

    def emit(self, event: dict) -> dict:
        """Stamp ``event`` with seq + monotonic ts, buffer it, and fan out."""
        stamped = {**event, "seq": next(self._seq), "ts": time.monotonic()}
        self._history.append(stamped)
        for queue in list(self._subscribers):
            queue.put_nowait(stamped)
        return stamped

    @property
    def history(self) -> list[dict]:
        return list(self._history)

    def last(self) -> dict | None:
        return self._history[-1] if self._history else None

    async def subscribe(self) -> AsyncIterator[dict]:
        """Yield buffered history, then live events, ending on a terminal event."""
        queue: asyncio.Queue = asyncio.Queue()
        for event in self._history:
            queue.put_nowait(event)
        self._subscribers.add(queue)
        try:
            # If we already emitted a terminal event, replay ends the stream.
            if self._history and self._history[-1].get("terminal"):
                for event in list(self._history):
                    yield event
                return
            while True:
                event = await queue.get()
                yield event
                if event.get("terminal"):
                    return
        finally:
            self._subscribers.discard(queue)

    def close(self) -> None:
        self.closed = True
