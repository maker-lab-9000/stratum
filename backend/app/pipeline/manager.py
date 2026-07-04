"""In-process job manager (spec §9 — background tasks, configurable concurrency).

Owns the job queue, one ``JobBus`` per report, and cancellation. ``submit`` is
all ``POST /api/analyses`` (T10) needs: enqueue and return. A semaphore caps how
many analyses run at once; extra jobs wait (their reports stay ``queued`` until a
slot frees).
"""

from __future__ import annotations

import asyncio

from app.pipeline.events import JobBus
from app.pipeline.orchestrator import PipelineDeps, default_deps, run_analysis


class PipelineManager:
    def __init__(self, repo, *, concurrency: int = 2, deps: PipelineDeps | None = None, vantage: str | None = None) -> None:
        self._repo = repo
        self._deps = deps or default_deps()
        self._vantage = vantage
        self._semaphore = asyncio.Semaphore(concurrency)
        self._buses: dict[str, JobBus] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def submit(self, report_id: str, url: str, options: dict) -> JobBus:
        """Enqueue an analysis. Returns its JobBus (for streaming)."""
        bus = JobBus()
        self._buses[report_id] = bus
        self._tasks[report_id] = asyncio.create_task(self._run(report_id, url, options, bus))
        return bus

    async def _run(self, report_id: str, url: str, options: dict, bus: JobBus) -> None:
        try:
            async with self._semaphore:
                await run_analysis(
                    report_id, url, options,
                    repo=self._repo, emit=bus.emit, deps=self._deps, vantage=self._vantage,
                )
        except asyncio.CancelledError:
            # Cancelled before/while running: ensure a terminal state exists.
            report = self._repo.get(report_id)
            if report is not None and report.status not in ("done", "error"):
                self._repo.update(report_id, status="error", error="cancelled")
                bus.emit({"stage": "pipeline", "status": "error", "terminal": True, "error": "cancelled"})
        finally:
            bus.close()

    def cancel(self, report_id: str) -> bool:
        """Cancel a running/queued job. Returns True if a task was cancelled."""
        task = self._tasks.get(report_id)
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    def get_bus(self, report_id: str) -> JobBus | None:
        return self._buses.get(report_id)

    async def wait(self, report_id: str) -> None:
        """Await a job to finish (test/shutdown helper)."""
        task = self._tasks.get(report_id)
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
