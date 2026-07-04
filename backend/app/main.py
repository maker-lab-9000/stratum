"""Production FastAPI app: real repository + pipeline manager, wired from env.

The LLM ``analyze`` callable is still None until T12, so live runs produce the
degraded verdict — the full evidence pipeline and API are otherwise complete.
"""

from __future__ import annotations

import os

from app.api.factory import create_app
from app.db import get_engine, get_repository, init_db
from app.pipeline.manager import PipelineManager
from app.pipeline.orchestrator import default_deps

# Create-on-boot (spec §6).
init_db(get_engine())

_repo = get_repository()
_manager = PipelineManager(
    _repo,
    concurrency=int(os.getenv("PIPELINE_CONCURRENCY", "2")),
    deps=default_deps(analyze=None),  # T12 wires the real LLM analyze
    vantage=os.getenv("VANTAGE_LABEL", "unknown vantage"),
)

app = create_app(_repo, _manager)
