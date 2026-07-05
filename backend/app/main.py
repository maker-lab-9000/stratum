"""Production FastAPI app: real repository + pipeline manager, wired from env.

The full analysis pipeline is now complete: the real LLM `analyze` callable
(provider → analysis call → evidence validator) is wired in, degrading to an
"unavailable" verdict — never losing evidence — when no provider is configured
or the LLM fails.
"""

from __future__ import annotations

import logging
import os

from app.api.factory import create_app
from app.db import get_engine, get_repository, init_db
from app.geoip import build_geo_provider
from app.pipeline.analyze import make_llm_analyze
from app.pipeline.manager import PipelineManager
from app.pipeline.orchestrator import default_deps

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# Create-on-boot (spec §6).
init_db(get_engine())

# Offline ASN/geo enrichment: MaxMind when available, else degrades to "unknown"
# (build_geo_provider never raises — a geo failure must not stop boot).
_geo = build_geo_provider()

_repo = get_repository()
# A restart drops any in-flight in-process jobs; don't leave their rows stuck
# in `running`/`queued` (§restart). Reconcile before accepting new work.
_interrupted = _repo.fail_unfinished(reason="interrupted by restart")
if _interrupted:
    logging.getLogger(__name__).warning("marked %d interrupted report(s) as error", _interrupted)

_manager = PipelineManager(
    _repo,
    concurrency=int(os.getenv("PIPELINE_CONCURRENCY", "2")),
    deps=default_deps(analyze=make_llm_analyze(), geo=_geo),
    vantage=os.getenv("VANTAGE_LABEL", "unknown vantage"),
)

app = create_app(_repo, _manager)
