"""Production FastAPI app: real repository + pipeline manager, wired from env.

The full analysis pipeline is now complete: the real LLM `analyze` callable
(provider → analysis call → evidence validator) is wired in, degrading to an
"unavailable" verdict — never losing evidence — when no provider is configured
or the LLM fails.
"""

from __future__ import annotations

import os

from app.api.factory import create_app
from app.db import get_engine, get_repository, init_db
from app.pipeline.analyze import make_llm_analyze
from app.pipeline.manager import PipelineManager
from app.pipeline.orchestrator import default_deps

# Create-on-boot (spec §6).
init_db(get_engine())

_repo = get_repository()
_manager = PipelineManager(
    _repo,
    concurrency=int(os.getenv("PIPELINE_CONCURRENCY", "2")),
    deps=default_deps(analyze=make_llm_analyze()),
    vantage=os.getenv("VANTAGE_LABEL", "unknown vantage"),
)

app = create_app(_repo, _manager)
