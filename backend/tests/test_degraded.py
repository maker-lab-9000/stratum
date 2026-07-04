"""T14 — degraded path & re-run (spec §5.2 failure paragraph, §8.3).

Scenarios:
  1. LLM fails twice -> report done, llm_json null + reason, evidence populated.
  2. GET report in degraded state -> frontend-parseable shape (T18 fixture).
  3. Provider auth error (non-retryable) -> no second call, degraded immediately.
  4. Re-run of a degraded report -> fresh id, original untouched.

Done-when: killing the LLM cannot lose evidence or wedge a job in `running`.
"""

import dataclasses
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.factory import create_app
from app.llm.base import ProviderError
from app.pipeline.analyze import make_llm_analyze
from app.pipeline.manager import PipelineManager
from app.pipeline.orchestrator import run_analysis
from tests.test_analysis import VALID_RESULT, FakeProvider
from tests.test_pipeline import URL, make_deps

BUNDLE = json.loads(
    (Path(__file__).parent / "fixtures" / "bundle" / "golden_bundle.json").read_text()
)
DEGRADED_FIXTURE = Path(__file__).parent / "fixtures" / "reports" / "degraded_report.json"


class RaisingProvider:
    """Raises a preset exception on analyze; counts calls."""

    id = "raising"
    name = "Raising"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    def static_models(self):
        return []

    async def list_models(self):
        return []

    async def analyze(self, *, system, user, model, settings):
        self.calls += 1
        raise self._exc


# --- analyze() unit behavior --------------------------------------------------

async def test_two_invalid_responses_degrade():
    provider = FakeProvider(["not json", "still not json"])
    analyze = make_llm_analyze(resolver=lambda name: provider)
    out = await analyze(BUNDLE, "fake", "m")

    assert out["verdict_json"]["status"] == "unavailable"
    assert "invalid output" in out["verdict_json"]["reason"]
    assert out["llm_json"] is None
    assert len(provider.calls) == 2  # retried once


async def test_auth_error_no_retry_degrades_immediately():
    provider = RaisingProvider(
        ProviderError("bad key", provider="anthropic", retryable=False, kind="auth")
    )
    analyze = make_llm_analyze(resolver=lambda name: provider)
    out = await analyze(BUNDLE, "anthropic", "m")

    assert provider.calls == 1  # no second call (§scenario 3)
    assert out["verdict_json"]["status"] == "unavailable"
    assert "auth" in out["verdict_json"]["reason"]


async def test_unknown_provider_degrades():
    analyze = make_llm_analyze(resolver=lambda name: None)
    out = await analyze(BUNDLE, "nope", "m")
    assert out["verdict_json"]["status"] == "unavailable"
    assert "not configured" in out["verdict_json"]["reason"]


async def test_success_path_validates_and_returns_verdict():
    provider = FakeProvider([json.dumps(VALID_RESULT)])
    analyze = make_llm_analyze(resolver=lambda name: provider)
    out = await analyze(BUNDLE, "fake", "m")
    # Validated verdict (not unavailable) with the validation report embedded.
    assert out["verdict_json"]["provider"] == "Akamai"
    assert out["verdict_json"]["validation"]["ok"] is True
    assert out["llm_json"]["cache_verdict"]["serving_layer"] == "Apache Dispatcher"


# --- Scenario 1: full pipeline degrades, evidence intact, not wedged ----------

async def test_pipeline_degrades_done_with_evidence(repo):
    report = repo.create(url=URL, provider="anthropic", model="claude-opus-4-8")
    deps = dataclasses.replace(
        make_deps(),
        analyze=make_llm_analyze(resolver=lambda name: FakeProvider(["bad", "bad again"])),
    )
    events: list[dict] = []
    await run_analysis(report.id, URL, {}, repo=repo, emit=events.append, deps=deps,
                       provider="anthropic", model="claude-opus-4-8")

    saved = repo.get(report.id)
    assert saved.status == "done"  # not error, not wedged in running
    assert saved.verdict_json["status"] == "unavailable"
    assert saved.llm_json is None
    # All evidence intact.
    assert saved.dns_json["a"]
    assert len(saved.samples_json) == 4
    assert saved.traceroute_json["hops"]
    # Stream emitted a degraded terminal event.
    assert events[-1]["terminal"] is True and events[-1]["degraded"] is True


# --- Scenario 2: degraded report fixture is frontend-parseable ----------------

def test_degraded_report_fixture_shape():
    report = json.loads(DEGRADED_FIXTURE.read_text())
    # The T18 contract for a degraded report.
    assert report["status"] == "done"
    assert report["verdict_json"] == {
        "status": "unavailable",
        "reason": "LLM returned invalid output after 2 attempts",
    }
    assert report["llm_json"] is None
    # Evidence still renders.
    assert report["dns_json"]["cname_chain"]
    assert len(report["samples_json"]) == 4
    assert report["traceroute_json"]["hops"]
    assert report["vantage"]  # §10 vantage disclosed even when degraded


# --- Scenarios 3 & 4 via the API ---------------------------------------------

@pytest.fixture
def degraded_api(repo):
    # Manager whose LLM always fails -> every run degrades.
    deps = dataclasses.replace(
        make_deps(sleep=0.02),
        analyze=make_llm_analyze(resolver=lambda name: FakeProvider(["x", "y"])),
    )
    manager = PipelineManager(repo, concurrency=2, deps=deps, vantage="Berlin, DE")
    return create_app(repo, manager, serve_static=False)


@pytest.fixture
async def client(degraded_api):
    async with AsyncClient(transport=ASGITransport(app=degraded_api), base_url="http://test") as c:
        yield c


async def test_rerun_creates_fresh_report_original_untouched(client, degraded_api):
    body = {"url": "https://www.example-foods.com/", "provider": "anthropic", "model": "claude-opus-4-8"}
    first_id = (await client.post("/api/analyses", json=body)).json()["id"]
    await degraded_api.state.manager.wait(first_id)
    first = (await client.get(f"/api/analyses/{first_id}")).json()
    assert first["status"] == "done" and first["verdict_json"]["status"] == "unavailable"

    # Re-run -> a new id, same url/provider/model.
    rerun = await client.post(f"/api/analyses/{first_id}/rerun")
    assert rerun.status_code == 201
    new_id = rerun.json()["id"]
    assert new_id != first_id
    await degraded_api.state.manager.wait(new_id)

    new = (await client.get(f"/api/analyses/{new_id}")).json()
    assert new["url"] == first["url"]
    assert new["provider"] == "anthropic" and new["model"] == "claude-opus-4-8"
    # Original untouched.
    still = (await client.get(f"/api/analyses/{first_id}")).json()
    assert still["id"] == first_id and still["created_at"] == first["created_at"]


async def test_rerun_unknown_404(client):
    assert (await client.post("/api/analyses/nope/rerun")).status_code == 404
