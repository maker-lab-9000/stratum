"""Shared pytest fixtures.

``repo`` gives every test a fresh, isolated SQLite-file repository (registered
in progress.md's fixture inventory — reuse it, don't rebuild it).
"""

import os

import pytest

from app.db.base import init_db, make_engine, make_session_factory
from app.db.repository import ReportRepository


@pytest.fixture
def session_factory(tmp_path):
    """A session factory bound to a throwaway SQLite file under tmp_path."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_engine(url)
    init_db(engine)
    return make_session_factory(engine)


@pytest.fixture
def repo(session_factory) -> ReportRepository:
    return ReportRepository(session_factory)


@pytest.fixture
def pg_repo():
    """Repository against a live Postgres, for @pytest.mark.postgres tests.

    Skips unless TEST_POSTGRES_URL is set (no Postgres in the default CI run;
    the docker-backed matrix is wired in T21/T24). Drops+recreates tables so the
    run is isolated.
    """
    dsn = os.getenv("TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("TEST_POSTGRES_URL not set")
    from app.db.base import Base

    engine = make_engine(dsn)
    Base.metadata.drop_all(engine)
    init_db(engine)
    try:
        yield ReportRepository(make_session_factory(engine))
    finally:
        Base.metadata.drop_all(engine)
