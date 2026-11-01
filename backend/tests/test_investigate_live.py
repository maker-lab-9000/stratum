"""Live investigate round-trip (1.4.0): a real Anthropic model, the real tool,
a local HTTP server. Excluded from the default run (``-m 'not live'``).

The server looks like a CDN edge that strips its hit/miss state (``Via``,
``Age: 0``, no cache status header) and says which debug request header reveals
it — the kind of situation investigate mode exists for.
The test asserts only that the loop made at least one tool round-trip and that
the extra sample was recorded; what the model concludes is not asserted.
"""

from __future__ import annotations

import os

import pytest

from app.collectors.http_sampler import sample_requests
from app.llm.anthropic import AnthropicProvider
from app.pipeline.analyze import make_llm_analyze
from app.pipeline.bundle import assemble_bundle
from tests.http_test_server import RawHTTPServer, build_response, received_header

MODEL = "claude-haiku-4-5"


async def _responder(count, request):
    headers = [("Server", "test-edge"), ("Via", "1.1 test-edge (TestCDN)"), ("Age", "0"),
               ("Cache-Control", "public, max-age=300"), ("Content-Type", "text/html"),
               ("X-Debug-Available", "send request header X-Stratum-Debug: 1 for the cache status")]
    if received_header(request, "X-Stratum-Debug") == "1":
        headers.append(("X-Test-Cache", "HIT from test-edge"))
        headers.append(("X-Test-Cache-TTL", "287"))
    return build_response(200, "OK", headers, b"<html>ok</html>")


@pytest.mark.live
async def test_live_investigate_round_trip():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    server = RawHTTPServer(_responder)
    await server.start()
    try:
        url = server.base_url + "/"
        samples = await sample_requests(url, request_count=2, cache_bust_probe=True)
        bundle = assemble_bundle(url=url, dns=None, samples=samples, warm=None, traceroute=None,
                                 enrichment=None, request_options={"investigate": True})
        provider = AnthropicProvider(key)
        analyze = make_llm_analyze(resolver=lambda name: provider)
        events: list[dict] = []
        out = await analyze(bundle, "anthropic", MODEL, emit=events.append)
    finally:
        await server.stop()

    log = out["llm_json"]["investigation_log"]
    assert len(log) >= 1, out["verdict_json"]
    assert any(e["stage"] == "investigate" for e in events)
    assert len(out["samples"]) == len(samples) + sum(1 for e in log if not e["refused"])
    assert out["samples"][-1]["probe"] == "investigation"
