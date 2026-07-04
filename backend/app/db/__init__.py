"""Database package.

For app code, use the process-wide singletons ``get_engine`` / ``get_repository``
(configured from ``DATABASE_URL``). Tests build their own engine/repository via
the ``make_*`` factories against a temp DB, so they never touch these.
"""

from functools import lru_cache

from sqlalchemy import Engine

from app.config import get_database_url
from app.db.base import Base, init_db, make_engine, make_session_factory
from app.db.models import Report
from app.db.repository import ReportRepository

__all__ = [
    "Base",
    "Report",
    "ReportRepository",
    "init_db",
    "make_engine",
    "make_session_factory",
    "get_engine",
    "get_repository",
]


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine(get_database_url())


@lru_cache(maxsize=1)
def get_repository() -> ReportRepository:
    return ReportRepository(make_session_factory(get_engine()))
