"""App factory: builds a FastAPI app around a repository + pipeline manager.

Kept separate from ``main`` so tests construct an app with fake pipeline deps and
a temp DB, while production wires the real singletons.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.api.routes import router


def create_app(repo, manager, *, serve_static: bool = True) -> FastAPI:
    app = FastAPI(title="Stratum", version="0.1.0")
    app.state.repo = repo
    app.state.manager = manager
    app.include_router(router)
    if serve_static:
        _mount_static(app)
    return app


def _mount_static(app: FastAPI) -> None:
    """Serve the built frontend single-origin (spec §8/§9) when present.

    The bundle only exists after `npm run build`; in dev the Vite proxy is used
    and in prod the T21 image builds it. Mounted last so /api/* wins.
    """
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")
