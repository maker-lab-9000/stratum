"""Runtime configuration read from the environment.

Secrets (LLM keys) are never read here into anything persisted — see spec §10.
"""

import os

DEFAULT_DATABASE_URL = "sqlite:///./data/stratum.db"


def get_database_url() -> str:
    """SQLite file by default; set DATABASE_URL to a Postgres DSN to switch (spec §6)."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def default_request_count() -> int:
    """Sampling fallback when a run doesn't specify one (§9.1 DEFAULT_REQUEST_COUNT)."""
    return int(os.getenv("DEFAULT_REQUEST_COUNT", "4"))


def default_interval_ms() -> int:
    """Inter-sample delay fallback (§9.1 DEFAULT_INTERVAL_MS)."""
    return int(os.getenv("DEFAULT_INTERVAL_MS", "0"))
