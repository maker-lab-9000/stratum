"""FastAPI application entrypoint.

Scaffold state: health endpoint + create-on-boot DB init. The analysis API,
pipeline, and streaming land in later tasks (see stratum-action-plan.md).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import get_engine, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create-on-boot (spec §6): ensure the reports table exists before serving.
    init_db(get_engine())
    yield


app = FastAPI(title="Stratum", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Liveness probe used by Docker/health checks and T01's smoke test."""
    return {"status": "ok"}
