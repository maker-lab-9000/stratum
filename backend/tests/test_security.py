"""T22 — security hardening (spec §10). One test per checklist line.

  1. AUTH_ENABLED gate: 401 without creds (health exempt), pass with; off → open.
  2. Outbound allowlist: off-list target rejected at POST with a clear error.
  3. Secrets: an LLM key value never appears in any API response or persisted row.
  4. (frontend) malicious headers render escaped — see report XSS tests.
  5. Vantage disclosed in every report payload.
"""

from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app import security
from app.api.factory import create_app
from app.pipeline.manager import PipelineManager
from tests.test_pipeline import make_deps

VANTAGE = "Berlin, DE · homelab"
SENTINEL_KEY = "sk-ant-SENTINEL-DO-NOT-LEAK-1234567890"


def _app(repo):
    manager = PipelineManager(repo, concurrency=2, deps=make_deps(sleep=0.02), vantage=VANTAGE)
    return create_app(repo, manager, serve_static=False)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _body(url="https://www.example-foods.com/"):
    return {"url": url, "provider": "anthropic", "model": "claude-opus-4-8"}


# --- Scenario 1: basic-auth gate ---------------------------------------------


async def test_auth_gate_blocks_without_credentials(repo, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("BASIC_AUTH_USER", "ops")
    monkeypatch.setenv("BASIC_AUTH_PASS", "hunter2")
    async with _client(_app(repo)) as c:
        # Health is exempt (container healthchecks).
        assert (await c.get("/api/health")).status_code == 200
        # Everything else needs credentials.
        assert (await c.get("/api/models")).status_code == 401
        assert (await c.post("/api/analyses", json=_body())).status_code == 401
        # Wrong password is rejected.
        assert (await c.get("/api/models", headers=_basic("ops", "wrong"))).status_code == 401
        # Correct credentials pass through.
        ok = await c.get("/api/models", headers=_basic("ops", "hunter2"))
        assert ok.status_code == 200


async def test_auth_disabled_is_open(repo, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    async with _client(_app(repo)) as c:
        assert (await c.get("/api/models")).status_code == 200


# --- Scenario 2: outbound allowlist ------------------------------------------


async def test_allowlist_rejects_offlist_target_at_post(repo, monkeypatch):
    monkeypatch.setenv("OUTBOUND_ALLOWLIST", "*.example-foods.com")
    async with _client(_app(repo)) as c:
        # Apex + subdomain of the allowed pattern pass.
        assert (await c.post("/api/analyses", json=_body("https://www.example-foods.com/x"))).status_code == 201
        assert (await c.post("/api/analyses", json=_body("https://example-foods.com/"))).status_code == 201
        # An unrelated host is rejected with a clear 400.
        resp = await c.post("/api/analyses", json=_body("https://evil.test/"))
        assert resp.status_code == 400
        assert "not in the outbound allowlist" in resp.json()["detail"]


def test_allowlist_matching_rules(monkeypatch):
    assert security.host_matches("api.example.com", "*.example.com")
    assert security.host_matches("example.com", "*.example.com")  # apex
    assert not security.host_matches("evilexample.com", "*.example.com")
    assert security.host_matches("exact.test", "exact.test")
    assert not security.host_matches("sub.exact.test", "exact.test")
    assert security.is_host_allowed("anything.test", [])  # empty allowlist = open


def test_private_target_detection():
    for host in ("127.0.0.1", "10.1.2.3", "192.168.0.5", "169.254.1.1", "::1"):
        assert security.is_private_target(host)
    for host in ("8.8.8.8", "23.55.142.16", "example.com"):
        assert not security.is_private_target(host)


# --- Scenario 3: secrets never leak ------------------------------------------


async def test_llm_key_never_appears_in_responses_or_db(repo, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    app = _app(repo)
    async with _client(app) as c:
        report_id = (await c.post("/api/analyses", json=_body())).json()["id"]
        await app.state.manager.wait(report_id)

        models_text = (await c.get("/api/models")).text
        report_text = (await c.get(f"/api/analyses/{report_id}")).text
        list_text = (await c.get("/api/analyses")).text
        for text in (models_text, report_text, list_text):
            assert SENTINEL_KEY not in text

    # And nowhere in the persisted row.
    row = repo.get(report_id)
    assert SENTINEL_KEY not in str(row.as_dict())


# --- Scenario 4: untrusted headers stored verbatim (rendered escaped in the UI) -


async def test_malicious_headers_are_stored_raw(repo):
    # The analysed site is untrusted; the backend stores its headers verbatim
    # (no sanitisation) — escaping happens only at render time (frontend tests).
    malicious = [
        ["x-xss", "<script>alert(1)</script>"],
        ["x-ansi", "\x1b[31mred\x1b[0m"],
        ["x-huge", "A" * 10_240],
    ]
    report = repo.create(url="https://untrusted.test/", provider="p", model="m", vantage=VANTAGE)
    repo.update(report.id, samples_json=[{"request": 1, "headers": malicious}])
    stored = repo.get(report.id).as_dict()["samples_json"][0]["headers"]
    assert stored == malicious  # byte-for-byte, unmodified


# --- Scenario 5: vantage disclosed -------------------------------------------


async def test_every_report_payload_discloses_vantage(repo):
    app = _app(repo)
    async with _client(app) as c:
        report_id = (await c.post("/api/analyses", json=_body())).json()["id"]
        # While running…
        assert (await c.get(f"/api/analyses/{report_id}")).json()["vantage"] == VANTAGE
        await app.state.manager.wait(report_id)
        # …and when done.
        assert (await c.get(f"/api/analyses/{report_id}")).json()["vantage"] == VANTAGE
        # …and in the history list row.
        listed = (await c.get("/api/analyses")).json()["reports"]
        assert all(r["vantage"] == VANTAGE for r in listed)
