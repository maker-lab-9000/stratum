"""T10 — REST API + SSE stream (spec §7).

Scenarios:
  1. POST -> {id}; report visible via GET while running, full after done.
  2. Invalid body (bad URL / request_count=0 / non-dict headers) -> 422.
  3. SSE: ordered stage events + terminal; late subscriber replays history.
  4. GET /api/analyses filters (domain, has_critical, provider) combine.
  5. DELETE running -> cancel+delete (204); on done -> gone; unknown -> 404.
  6. GET /api/models never contains key material.
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.factory import create_app
from app.pipeline.manager import PipelineManager
from tests.test_pipeline import make_deps

VANTAGE = "Berlin, DE · homelab"


@pytest.fixture
def api_app(repo):
    manager = PipelineManager(repo, concurrency=2, deps=make_deps(sleep=0.05), vantage=VANTAGE)
    return create_app(repo, manager, serve_static=False)


@pytest.fixture
async def client(api_app):
    async with AsyncClient(transport=ASGITransport(app=api_app), base_url="http://test") as c:
        yield c


def _body(url="https://www.example-foods.com/", **opts):
    body = {"url": url, "provider": "anthropic", "model": "claude-opus-4-8"}
    if opts:
        body["options"] = opts
    return body


# --- Scenario 1 ---------------------------------------------------------------

async def test_post_creates_and_get_returns_report(client, api_app):
    resp = await client.post("/api/analyses", json=_body(request_count=4))
    assert resp.status_code == 201
    report_id = resp.json()["id"]

    # Visible via GET while still running, with partial fields.
    got = await client.get(f"/api/analyses/{report_id}")
    assert got.status_code == 200
    data = got.json()
    assert data["id"] == report_id
    assert data["url"] == "https://www.example-foods.com/"
    assert data["status"] in ("queued", "running", "done")
    assert data["vantage"] == VANTAGE  # §10 vantage disclosed

    await api_app.state.manager.wait(report_id)
    done = (await client.get(f"/api/analyses/{report_id}")).json()
    assert done["status"] == "done"
    assert len(done["samples_json"]) == 4
    assert done["verdict_json"]["cached"] is True


async def test_get_unknown_report_404(client):
    assert (await client.get("/api/analyses/nope")).status_code == 404


# --- Scenario 2 ---------------------------------------------------------------

@pytest.mark.parametrize(
    "body",
    [
        {"url": "not-a-url", "provider": "p", "model": "m"},
        {"url": "ftp://x.test", "provider": "p", "model": "m"},
        {"url": "https://x.test", "provider": "p", "model": "m", "options": {"request_count": 0}},
        {"url": "https://x.test", "provider": "p", "model": "m", "options": {"extra_request_headers": ["a", "b"]}},
        {"url": "https://x.test", "provider": "", "model": "m"},
    ],
)
async def test_invalid_bodies_422(client, body):
    resp = await client.post("/api/analyses", json=body)
    assert resp.status_code == 422
    assert "detail" in resp.json()


# --- Scenario 3 ---------------------------------------------------------------

async def _collect_stream(client, report_id):
    events = []
    async with client.stream("GET", f"/api/analyses/{report_id}/stream") as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                event = json.loads(line[len("data: "):])
                events.append(event)
                if event.get("terminal"):
                    break
    return events


async def test_sse_stream_ordered_with_terminal(client, api_app):
    report_id = (await client.post("/api/analyses", json=_body())).json()["id"]
    events = await _collect_stream(client, report_id)

    assert events[0]["stage"] == "pipeline" and events[0]["status"] == "running"
    assert events[-1]["terminal"] is True
    assert events[-1]["stage"] == "pipeline"
    # Partial results ride along: the sample-completed event carries the samples.
    sample_event = next(e for e in events if e["stage"] == "sample" and e["status"] == "completed")
    assert sample_event["data"]
    await api_app.state.manager.wait(report_id)


async def test_sse_late_subscriber_replays_history(client, api_app):
    report_id = (await client.post("/api/analyses", json=_body())).json()["id"]
    await api_app.state.manager.wait(report_id)  # finished before we subscribe

    events = await _collect_stream(client, report_id)
    statuses = [(e["stage"], e["status"]) for e in events]
    assert ("pipeline", "running") in statuses
    assert events[-1]["terminal"] is True


# --- Scenario 4 ---------------------------------------------------------------

async def test_list_filters_combine(client, repo):
    repo.create(url="https://shop.example-foods.com/a", provider="anthropic",
                llm_json={"security_findings": [{"severity": "critical"}], "performance_findings": []})
    repo.create(url="https://blog.example-foods.com/b", provider="openrouter")
    repo.create(url="https://www.other.test/c", provider="anthropic")

    domain = (await client.get("/api/analyses?domain=example-foods.com")).json()["reports"]
    assert len(domain) == 2 and all("example-foods.com" in r["url"] for r in domain)

    crit = (await client.get("/api/analyses?has_critical=true")).json()["reports"]
    assert len(crit) == 1

    combo = (await client.get("/api/analyses?domain=example-foods.com&provider=anthropic")).json()["reports"]
    assert len(combo) == 1


# --- Scenario 5 ---------------------------------------------------------------

async def test_delete_running_cancels_and_removes(client, api_app):
    report_id = (await client.post("/api/analyses", json=_body())).json()["id"]
    resp = await client.delete(f"/api/analyses/{report_id}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/analyses/{report_id}")).status_code == 404
    await api_app.state.manager.wait(report_id)  # settle the cancelled task


async def test_delete_unknown_404(client):
    assert (await client.delete("/api/analyses/nope")).status_code == 404


# --- Scenario 6 ---------------------------------------------------------------

async def test_models_no_key_material(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-abc123")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    resp = await client.get("/api/models")
    assert resp.status_code == 200
    assert "sk-ant-secret-abc123" not in resp.text  # never leak the key

    providers = {p["id"]: p for p in resp.json()["providers"]}
    assert "anthropic" in providers
    assert providers["anthropic"]["models"]
    assert "openrouter" not in providers  # key absent -> provider absent


async def test_models_empty_when_no_keys(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    resp = await client.get("/api/models")
    assert resp.json()["providers"] == []


# --- T24: SPA fallback for the single-origin static mount ---------------------

async def test_spa_fallback_serves_index_for_client_routes(tmp_path):
    from fastapi import FastAPI

    from app.api.factory import _SPAStaticFiles

    (tmp_path / "index.html").write_text("<!doctype html><title>APP</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('x')")

    app = FastAPI()
    app.mount("/", _SPAStaticFiles(directory=str(tmp_path), html=True), name="static")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Real asset served normally.
        assert (await c.get("/assets/app.js")).status_code == 200
        # Client-side routes (deep link / refresh) fall back to index.html.
        for path in ("/history", "/reports/abc123", "/runs/xyz"):
            resp = await c.get(path)
            assert resp.status_code == 200
            assert "APP" in resp.text


# --- 1.0.1: live per-provider model listing (GET /api/models/{provider}) ------

async def test_provider_models_live_list(client, monkeypatch):
    import httpx
    import respx

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    with respx.mock:
        respx.get("https://openrouter.ai/api/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={"data": [
                    {"id": "anthropic/claude-opus-4-8", "name": "Claude Opus 4.8"},
                    {"id": "openai/gpt-5", "name": "GPT-5"},
                    {"id": "meta-llama/llama-3", "name": "Llama 3"},
                ]},
            )
        )
        resp = await client.get("/api/models/openrouter")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "openrouter"
    assert [m["id"] for m in body["models"]] == [
        "anthropic/claude-opus-4-8", "openai/gpt-5", "meta-llama/llama-3",
    ]
    # No key material ever leaks into the response (§10).
    assert "sk-or-test" not in resp.text


async def test_provider_models_falls_back_to_static_on_upstream_error(client, monkeypatch):
    import httpx
    import respx

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    with respx.mock:
        respx.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(500))
        resp = await client.get("/api/models/openrouter")
    assert resp.status_code == 200  # degrades, never errors
    assert len(resp.json()["models"]) > 0  # the provider's static list


async def test_provider_models_unknown_provider_404(client, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = await client.get("/api/models/openrouter")
    assert resp.status_code == 404
