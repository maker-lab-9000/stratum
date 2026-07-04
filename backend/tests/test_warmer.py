"""T05 — Playwright warmer (spec §3.2).

Scenarios:
  1. Real navigation against a local server (browser-like, JS-capable client).
  2. warm=false -> no navigation performed.
  3. Navigation timeout -> {warmed: false, error}, pipeline continues (degraded).
  4. Timing fields present when navigation succeeds.

Done-criterion: fire-and-continue — no Playwright exception can abort a run.

The contract (1-4 except the real nav) is unit-tested with a fake Navigator.
The real navigation is chromium-gated: it runs when the browser is installed,
otherwise skips (keeps a fresh clone's `make test` green without the browser).
"""

import json
import os

import pytest

from app.collectors.warmer import PlaywrightNavigator, warm_cache
from tests.http_test_server import RawHTTPServer, build_response, received_header


class FakeNavigator:
    def __init__(self, timing=None, raise_exc=None):
        self._timing = timing if timing is not None else {"status": 200, "load_ms": 123}
        self._raise = raise_exc
        self.calls: list[tuple[str, int]] = []

    async def navigate(self, url, *, timeout_ms):
        self.calls.append((url, timeout_ms))
        if self._raise is not None:
            raise self._raise
        return self._timing


# --- Scenario 2 ---------------------------------------------------------------

async def test_warm_false_performs_no_navigation():
    nav = FakeNavigator()
    result = await warm_cache("https://example.com", warm=False, navigator=nav)
    assert result == {"warmed": False, "skipped": True, "error": None, "timing": None}
    assert nav.calls == []  # navigator never invoked


# --- Scenario 4 ---------------------------------------------------------------

async def test_success_returns_timing():
    nav = FakeNavigator(timing={"status": 200, "ttfb_ms": 40, "load_ms": 210})
    result = await warm_cache("https://example.com", navigator=nav)
    assert result["warmed"] is True
    assert result["skipped"] is False
    assert result["error"] is None
    assert result["timing"]["load_ms"] == 210
    assert nav.calls == [("https://example.com", 15_000)]
    assert json.loads(json.dumps(result)) == result


# --- Scenario 3 ---------------------------------------------------------------

async def test_timeout_is_non_fatal():
    nav = FakeNavigator(raise_exc=TimeoutError("navigation exceeded 15000ms"))
    result = await warm_cache("https://example.com", navigator=nav)
    assert result["warmed"] is False
    assert result["skipped"] is False
    assert result["timing"] is None
    assert "TimeoutError" in result["error"]


async def test_any_exception_is_non_fatal():
    nav = FakeNavigator(raise_exc=RuntimeError("browser crashed"))
    result = await warm_cache("https://example.com", navigator=nav)
    assert result["warmed"] is False
    assert "RuntimeError" in result["error"]


async def test_missing_browser_binary_is_non_fatal(monkeypatch):
    # Even the real navigator failing to launch (e.g. no browser installed) must
    # degrade, never raise — that is the whole done-criterion.
    async def boom(self, url, *, timeout_ms):
        raise RuntimeError("Executable doesn't exist; run `playwright install`")

    monkeypatch.setattr(PlaywrightNavigator, "navigate", boom)
    result = await warm_cache("https://example.com")  # real navigator, patched
    assert result["warmed"] is False
    assert result["error"] and "RuntimeError" in result["error"]


# --- Scenario 1 + 4 (real navigation, chromium-gated) -------------------------

def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            path = pw.chromium.executable_path
            return bool(path) and os.path.exists(path)
    except Exception:
        return False


requires_chromium = pytest.mark.skipif(
    not _chromium_available(), reason="Chromium not installed (run: playwright install chromium)"
)


@requires_chromium
async def test_real_navigation_against_local_server():
    async def responder(count, request):
        return build_response(200, "OK", [("Cache-Control", "max-age=60")], b"<html><body>hi</body></html>")

    server = RawHTTPServer(responder)
    await server.start()
    try:
        result = await warm_cache(server.base_url + "/", timeout_ms=15_000)
    finally:
        await server.stop()

    # Scenario 1: a real navigation happened and the server saw a browser.
    assert result["warmed"] is True, result
    assert len(server.received) >= 1
    ua = received_header(server.received[0], "User-Agent") or ""
    assert "Chrome" in ua or "HeadlessChrome" in ua or "Mozilla" in ua
    # Scenario 4: timing fields present on success.
    assert result["timing"]["status"] == 200
    assert "load_ms" in result["timing"]
    assert json.loads(json.dumps(result)) == result
