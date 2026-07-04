"""FastAPI application entrypoint.

T01 scaffold: only the health endpoint exists. Pipeline, persistence, and the
analysis API land in later tasks (see stratum-action-plan.md).
"""

from fastapi import FastAPI

app = FastAPI(title="Stratum", version="0.1.0")


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Liveness probe used by Docker/health checks and T01's smoke test."""
    return {"status": "ok"}
