"""1.0.2 regression: multi-CDN with a clobbered inner-cache hit token.

The persil.de case — CloudFront fronts a Fastly/Varnish cache. CloudFront
overwrites the inner cache's `x-cache` with its own `Miss from cloudfront`, so
the only proof the object is cached is a non-zero `Age` plus leaked Fastly
fingerprints (`x-served-by: cache-*`, `x-timer`). Before 1.0.2 the model
narrated the Fastly tier but the structured verdict said `cached: false` with a
CloudFront-only chain.

Two guards:
- deterministic: the *corrected* verdict's citations (notably `age: 226`) all
  exist in the bundle, so the fix the prompt now asks for is machine-checkable;
- live (opt-in): the real model, on this bundle, must not call it uncached.
"""

from __future__ import annotations

import os

import pytest

from app.llm.registry import get_provider
from app.llm.analysis import run_analysis
from app.pipeline.analyze import make_llm_analyze
from app.pipeline.bundle import assemble_bundle
from tests.test_analysis import FakeProvider
import json


def _persil_sample(request: int, served_by: str) -> dict:
    return {
        "request": request,
        "ok": True,
        "status": 200,
        "http_version": "HTTP/2",
        "url": "https://www.persil.de/produkte.html",
        "headers": [
            ["server", "CloudFront"],
            ["cache-control", "max-age=900,stale-while-revalidate=604800"],
            ["server-timing", "cdn-cache;dur=226"],
            ["age", "226"],
            ["x-served-by", served_by],
            ["x-timer", "S1783517666.390675,VS0,VS0,VE5"],
            ["via", "1.1 3036edceee55768c8dc6fc7bbe13d08e.cloudfront.net (CloudFront)"],
            ["x-cache", "Miss from cloudfront"],
            ["x-amz-cf-pop", "TXL50-P4"],
        ],
        "elapsed_ms": 40 + request,
        "started_at_ms": request,
        "error": None,
    }


PERSIL_BUNDLE = assemble_bundle(
    url="https://www.persil.de/produkte.html",
    dns={"a": ["18.64.119.98"], "aaaa": [], "cname_chain": [
        {"name": "www.persil.de", "cname": "d3fcbz57t4izbt.cloudfront.net", "ttl": 77}],
        "ns": ["ns-1292.awsdns-33.org"], "ttl": 77},
    samples=[
        _persil_sample(1, "cache-fra-etou8220155-FRA"),
        _persil_sample(2, "cache-fra-etou8220137-FRA"),
        _persil_sample(3, "cache-fra-etou8220097-FRA"),
        _persil_sample(4, "cache-fra-etou8220071-FRA"),
    ],
    warm=None,
    traceroute={"hops": [{"n": 2, "ip": "18.64.119.98", "org": "Amazon.com, Inc.", "asn": 16509}]},
    enrichment=None,
    vantage="e2e vantage",
)

# The corrected verdict: CloudFront edge PASS-THROUGH, an inner shared cache HIT
# cited from the non-zero Age + the leaked Fastly fingerprint.
CORRECTED = {
    "cache_verdict": {
        "cached": True,
        "confidence": "medium",
        "provider": "Amazon CloudFront (edge) fronting a Fastly/Varnish cache",
        "provider_evidence": ["via: 1.1 3036edceee55768c8dc6fc7bbe13d08e.cloudfront.net (CloudFront)"],
        "serving_layer": "Fastly shared cache",
        "layer_count_to_origin": 2,
        "layers": [
            {"layer_name": "CloudFront edge", "vendor": "Amazon CloudFront", "cache_type": "CDN edge",
             "role": "edge", "caches": True, "state": "MISS",
             "evidence_headers": ["x-cache: Miss from cloudfront"]},
            {"layer_name": "Fastly shared cache", "vendor": "Fastly", "cache_type": "shared HTTP cache",
             "role": "shield", "caches": True, "state": "HIT",
             "evidence_headers": ["age: 226", "x-served-by: cache-fra-etou8220155-FRA"]},
        ],
        "sample_states": [
            {"request": 1, "state": "HIT", "evidence_headers": ["age: 226"]},
            {"request": 2, "state": "HIT", "evidence_headers": ["age: 226"]},
        ],
    },
    "overall_summary": "CloudFront edge passes through (MISS); a downstream Fastly cache serves the object (age 226).",
    "segment_narration": [
        {"segment": "CDN network", "hop_range": "2", "description": "CloudFront edge, Berlin",
         "corroboration": "AS16509 Amazon.com, Inc."},
    ],
    "security_findings": [],
    "performance_findings": [
        {"severity": "warning", "title": "CloudFront edge not caching",
         "description": "All samples MISS at the edge.", "evidence_header": "x-cache: Miss from cloudfront"},
    ],
}


async def test_corrected_multicdn_verdict_validates():
    analyze = make_llm_analyze(resolver=lambda _name: FakeProvider([json.dumps(CORRECTED)]))
    out = await analyze(PERSIL_BUNDLE, "fake", "m")
    verdict = out["verdict_json"]

    # The fix is realizable: it's cached, served downstream of the edge, and every
    # citation (incl. `age: 226`) exists in the captured data.
    assert verdict["cached"] is True
    assert verdict["serving_layer"] == "Fastly shared cache"
    assert verdict["validation"]["ok"] is True
    assert verdict["validation"]["flags"] == []
    # The serving layer is NOT the CloudFront edge.
    serving = next(l for l in verdict["layers"] if l["layer_name"] == verdict["serving_layer"])
    assert serving["role"] != "edge"
    assert serving["state"] == "HIT"


@pytest.mark.live
async def test_live_model_does_not_call_persil_uncached():
    provider_name = "anthropic" if os.getenv("ANTHROPIC_API_KEY") else (
        "openrouter" if os.getenv("OPENROUTER_API_KEY") else None
    )
    if provider_name is None:
        pytest.skip("no LLM key set")
    provider = get_provider(provider_name)
    model = provider.static_models()[0]["id"]
    result = await run_analysis(PERSIL_BUNDLE, provider=provider, model=model)

    v = result.cache_verdict
    assert v.cached is True, "non-zero Age must not be read as uncached"
    serving = next((l for l in v.layers if l.layer_name == v.serving_layer), None)
    # Serving layer exists and is not the outer CloudFront edge passthrough.
    assert serving is not None and serving.role != "edge"
