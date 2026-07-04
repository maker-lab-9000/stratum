"""Runtime configuration read from the environment.

Secrets (LLM keys) are never read here into anything persisted — see spec §10.
"""

import os

DEFAULT_DATABASE_URL = "sqlite:///./data/stratum.db"


def get_database_url() -> str:
    """SQLite file by default; set DATABASE_URL to a Postgres DSN to switch (spec §6)."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
