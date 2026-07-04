"""SQLAlchemy engine/session plumbing.

Synchronous SQLAlchemy 2.0 is used deliberately (see progress.md decisions):
at single-operator homelab scale it is simpler and less bug-prone than mixing
async drivers, and FastAPI runs blocking repository calls in its threadpool.

Portability: the generic ``JSON`` column type works on both SQLite (JSON1) and
Postgres, so the same models/repository run against either via ``DATABASE_URL``.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def make_engine(url: str) -> Engine:
    """Build an Engine for a SQLite file/memory URL or a Postgres DSN."""
    connect_args: dict = {}
    if url.startswith("sqlite"):
        # Allow use across FastAPI's threadpool.
        connect_args["check_same_thread"] = False
        _ensure_sqlite_parent_dir(url)
    return create_engine(url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    # expire_on_commit=False keeps attributes readable on detached objects the
    # repository returns after a session closes (models have no relationships).
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create tables if absent (create-on-boot; spec §6 allows this over Alembic)."""
    # Import models so they register on Base.metadata before create_all.
    from app.db import models  # noqa: F401

    Base.metadata.create_all(engine)


def _ensure_sqlite_parent_dir(url: str) -> None:
    # url form: sqlite:///relative/path.db or sqlite:////absolute/path.db
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return
    path_part = url[len(prefix):]
    if not path_part or path_part == ":memory:":
        return
    parent = Path(path_part).parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
