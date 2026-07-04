"""REST endpoints + SSE stream (spec §7).

Handlers read the shared ``ReportRepository`` and ``PipelineManager`` off
``request.app.state`` (wired by the app factory). POST only enqueues — all the
work is the pipeline's (T09).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.schemas import CreateAnalysisRequest, CreateAnalysisResponse
from app.llm.catalog import available_models

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/models")
async def get_models() -> dict:
    # Never includes key material — only ids/names (spec §10).
    return available_models()


@router.post("/analyses", response_model=CreateAnalysisResponse, status_code=status.HTTP_201_CREATED)
async def create_analysis(body: CreateAnalysisRequest, request: Request) -> CreateAnalysisResponse:
    repo = request.app.state.repo
    manager = request.app.state.manager

    report = repo.create(
        url=body.url,
        provider=body.provider,
        model=body.model,
        vantage=manager.vantage,
    )
    manager.submit(report.id, body.url, body.options.model_dump())
    return CreateAnalysisResponse(id=report.id)


@router.get("/analyses")
async def list_analyses(
    request: Request,
    domain: str | None = Query(default=None),
    has_critical: bool | None = Query(default=None),
    provider: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    repo = request.app.state.repo
    reports = repo.list(
        domain=domain, has_critical=has_critical, provider=provider, limit=limit, offset=offset
    )
    return {"reports": [r.as_dict() for r in reports]}


@router.get("/analyses/{report_id}")
async def get_analysis(report_id: str, request: Request) -> dict:
    report = request.app.state.repo.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return report.as_dict()


@router.delete("/analyses/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(report_id: str, request: Request) -> Response:
    repo = request.app.state.repo
    manager = request.app.state.manager
    report = repo.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    # Policy: DELETE cancels a running job, then removes the row. The cancelled
    # task updating a now-deleted row is a safe no-op (repo.update -> None).
    manager.cancel(report_id)
    repo.delete(report_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/analyses/{report_id}/stream")
async def stream_analysis(report_id: str, request: Request) -> StreamingResponse:
    repo = request.app.state.repo
    manager = request.app.state.manager

    bus = manager.get_bus(report_id)
    if bus is None:
        # No live job (unknown id, or a finished job after a restart): emit the
        # current persisted state once as a terminal event (replay policy).
        report = repo.get(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        snapshot = {
            "stage": "pipeline",
            "status": report.status,
            "terminal": True,
            "report": report.as_dict(),
        }

        async def snapshot_gen():
            yield _sse(snapshot)

        return StreamingResponse(snapshot_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)

    async def event_gen():
        # subscribe() replays buffered history first, then live events, so a late
        # subscriber gets current state before new events.
        async for event in bus.subscribe():
            yield _sse(event)

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
