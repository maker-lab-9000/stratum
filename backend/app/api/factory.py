"""App factory: builds a FastAPI app around a repository + pipeline manager.

Kept separate from ``main`` so tests construct an app with fake pipeline deps and
a temp DB, while production wires the real singletons.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.api.routes import router
from app.security import add_basic_auth


def create_app(repo, manager, *, serve_static: bool = True) -> FastAPI:
    app = FastAPI(title="Stratum", version="0.1.0")
    app.state.repo = repo
    app.state.manager = manager
    app.include_router(router)
    if serve_static:
        _mount_static(app)
    # Optional basic-auth gate (env-driven, off by default; §10). Added last so
    # it wraps the router + static mount alike.
    add_basic_auth(app)
    return app


def _mount_static(app: FastAPI) -> None:
    """Serve the built frontend single-origin (spec §8/§9) when present.

    The bundle only exists after `npm run build`; in dev the Vite proxy is used
    and in prod the T21 image builds it. Mounted after the router so /api/* wins.
    Uses an SPA fallback so a full navigation or refresh on a client-side route
    (e.g. /history, /reports/:id permalinks) serves index.html instead of 404ing.
    """
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", _SPAStaticFiles(directory=str(dist), html=True), name="static")


# Defined lazily-importable at module load; StaticFiles is a light import.
from starlette.exceptions import HTTPException as _StarletteHTTPException  # noqa: E402
from starlette.staticfiles import StaticFiles as _StaticFiles  # noqa: E402


class _SPAStaticFiles(_StaticFiles):
    """StaticFiles that falls back to index.html on a missing path, so React
    Router client routes deep-load and survive refresh (single-origin prod)."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except _StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise
