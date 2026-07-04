"""T04 — HTTP sampler (spec §3.3, §7 options).

Scenarios (all against a real raw HTTP/1.1 local server):
  1. N=4 -> 4 samples, full headers incl. duplicate Via preserved as two entries.
  2. Header name case preserved (X-Cache not lowercased).
  3. interval_ms=200 -> inter-request gaps >= ~200ms.
  4. extra_request_headers (Pragma) actually sent (asserted server-side).
  5. 500 / redirect recorded with status; redirect NOT followed.
  6. Timeout on request 3 of 4 -> 1-2 kept, 3 failed, 4 still attempted.
"""

import asyncio
import json

import pytest

from app.collectors.http_sampler import sample_requests
from tests.http_test_server import RawHTTPServer, build_response, received_header


async def _serve(responder):
    server = RawHTTPServer(responder)
    await server.start()
    return server


def _headers_of(sample) -> list[tuple[str, str]]:
    return [(k, v) for k, v in sample["headers"]]


def _header_values(sample, name) -> list[str]:
    return [v for k, v in sample["headers"] if k.lower() == name.lower()]


async def _default_responder(count, request):
    # Age climbs across samples; X-Cache goes MISS then HIT; two Via headers.
    age = (count - 1) * 12  # 0, 12, 24, 36
    state = "MISS" if count == 1 else "HIT"
    headers = [
        ("Via", "1.1 varnish"),
        ("Via", "1.1 edge"),
        ("X-Cache", f"TCP_{state} from a1"),
        ("Age", str(age)),
        ("Content-Type", "text/html"),
    ]
    return build_response(200, "OK", headers, b"<html>ok</html>")


# --- Scenario 1 + 2 -----------------------------------------------------------

async def test_four_samples_with_duplicates_and_case_preserved():
    server = await _serve(_default_responder)
    try:
        samples = await sample_requests(server.base_url + "/", request_count=4)
    finally:
        await server.stop()

    assert len(samples) == 4
    assert all(s["ok"] and s["status"] == 200 for s in samples)

    # Scenario 1: duplicate Via preserved as two entries.
    assert _header_values(samples[0], "Via") == ["1.1 varnish", "1.1 edge"]

    # Scenario 2: header name case preserved exactly as sent.
    names = [k for k, _ in samples[0]["headers"]]
    assert "X-Cache" in names
    assert "x-cache" not in names

    # Done-criterion: changed Age observable across samples.
    ages = [_header_values(s, "Age")[0] for s in samples]
    assert ages == ["0", "12", "24", "36"]

    # Serializes cleanly into samples_json.
    assert json.loads(json.dumps(samples)) == samples


# --- Scenario 3 ---------------------------------------------------------------

async def test_interval_spacing_respected():
    server = await _serve(_default_responder)
    try:
        samples = await sample_requests(
            server.base_url + "/", request_count=3, interval_ms=200
        )
    finally:
        await server.stop()

    starts = [s["started_at_ms"] for s in samples]
    gaps = [starts[i + 1] - starts[i] for i in range(len(starts) - 1)]
    # Each start-to-start gap includes the >=200ms sleep (allow timer slack).
    assert all(gap >= 190 for gap in gaps), gaps


# --- Scenario 4 ---------------------------------------------------------------

async def test_extra_request_headers_are_sent():
    server = await _serve(_default_responder)
    try:
        await sample_requests(
            server.base_url + "/",
            request_count=2,
            extra_request_headers={"Pragma": "akamai-x-get-cache-key"},
        )
    finally:
        await server.stop()

    assert len(server.received) == 2
    for req in server.received:
        assert received_header(req, "Pragma") == "akamai-x-get-cache-key"


# --- Scenario 5 ---------------------------------------------------------------

async def test_500_recorded_with_status():
    async def responder(count, request):
        return build_response(500, "Internal Server Error", [("X-Err", "1")], b"boom")

    server = await _serve(responder)
    try:
        samples = await sample_requests(server.base_url + "/", request_count=1)
    finally:
        await server.stop()

    assert samples[0]["ok"] is True  # got an HTTP response
    assert samples[0]["status"] == 500


async def test_redirect_not_followed():
    async def responder(count, request):
        return build_response(
            302, "Found", [("Location", "http://127.0.0.1:9/final")], b""
        )

    server = await _serve(responder)
    try:
        samples = await sample_requests(server.base_url + "/start", request_count=1)
    finally:
        await server.stop()

    assert samples[0]["status"] == 302
    # Not followed: the sampled URL stays the one we asked for.
    assert samples[0]["url"].endswith("/start")
    assert _header_values(samples[0], "Location") == ["http://127.0.0.1:9/final"]
    # Server only ever saw the one request (no auto-followed second hop).
    assert len(server.received) == 1


# --- Scenario 6 ---------------------------------------------------------------

async def test_timeout_on_third_request_keeps_others():
    async def responder(count, request):
        if count == 3:
            await asyncio.sleep(1.0)  # exceed the short client timeout below
        return await _default_responder(count, request)

    server = await _serve(responder)
    try:
        samples = await sample_requests(
            server.base_url + "/", request_count=4, timeout_ms=300
        )
    finally:
        await server.stop()

    assert len(samples) == 4
    assert samples[0]["ok"] and samples[1]["ok"]
    assert samples[2]["ok"] is False
    assert samples[2]["status"] is None
    assert "Timeout" in samples[2]["error"] or "timeout" in samples[2]["error"].lower()
    # Sample 4 was still attempted and succeeded.
    assert samples[3]["ok"] is True
    assert samples[3]["status"] == 200


# --- edge -------------------------------------------------------------------

async def test_zero_request_count_returns_empty():
    samples = await sample_requests("http://127.0.0.1:9/", request_count=0)
    assert samples == []


# --- Live smoke (excluded by default) ----------------------------------------

@pytest.mark.live
async def test_live_sampling_real_site():
    samples = await sample_requests("https://www.cloudflare.com/", request_count=2)
    assert len(samples) == 2
    assert all(s["ok"] and s["status"] in (200, 301, 302, 403) for s in samples)
    # Real responses carry headers, captured verbatim and JSON-serializable.
    assert samples[0]["headers"]
    assert samples[0]["http_version"] in ("HTTP/1.1", "HTTP/2")
    assert json.loads(json.dumps(samples)) == samples
