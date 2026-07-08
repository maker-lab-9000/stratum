"""T12 — analysis call: prompt + schema (spec §4.1–4.3, §4.5, §5.2, §5.3).

Scenarios (fake LLM):
  1. Golden path -> parsed StructuredResult, serving_layer == "Apache Dispatcher".
  2. Fenced / prose-wrapped response -> rejected, retried once, second parsed.
  3. Two invalid responses -> AnalysisParseError.
  4. Schema violation (missing evidence_headers / bad enum) -> retry triggered.
  5. Prompt snapshot: the four §5.3 constraints + vendor table present.
  6. Payload audit: user message = all N sample headers + enriched hops, no
     pre-computed vendor/hit fields. temp 0 asserted.
"""

import json
from pathlib import Path

import pytest

from app.llm.analysis import AnalysisParseError, run_analysis
from app.llm.prompt import SYSTEM_PROMPT
from app.llm.schema import StructuredResult

AKAMAI_BUNDLE = json.loads(
    (Path(__file__).parent / "fixtures" / "bundle" / "golden_bundle.json").read_text()
)

# A schema-valid canned verdict for the akamai-bypass story.
VALID_RESULT = {
    "cache_verdict": {
        "cached": False,
        "confidence": "high",
        "provider": "Akamai",
        "provider_evidence": ["example-foods.com.edgekey.net", "Via: 1.1 v1-akamaitech.net"],
        "serving_layer": "Apache Dispatcher",
        "layer_count_to_origin": 2,
        "layers": [
            {"layer_name": "Akamai Edge", "vendor": "Akamai", "cache_type": "CDN edge",
             "role": "edge", "caches": True, "state": "PASS",
             "evidence_headers": ["X-Cache: TCP_MISS from a23-fra"]},
            {"layer_name": "Apache Dispatcher", "vendor": "Apache/AEM", "cache_type": "reverse-proxy",
             "role": "reverse_proxy", "caches": True, "state": "HIT",
             "evidence_headers": ["Server: AkamaiGHost"]},
        ],
        "sample_states": [
            {"request": 1, "state": "MISS", "evidence_headers": ["X-Cache: TCP_MISS from a23-fra"]},
            {"request": 2, "state": "MISS", "evidence_headers": ["X-Cache: TCP_MISS from a23-fra"]},
        ],
    },
    "overall_summary": "CDN bypass: Akamai edge is not storing the object; served from the Apache Dispatcher.",
    "segment_narration": [
        {"segment": "Access", "hop_range": "1", "description": "Home LAN", "corroboration": "192.168.1.1"},
        {"segment": "CDN network", "hop_range": "2", "description": "Akamai edge, Frankfurt",
         "corroboration": "AS20940 Akamai Technologies"},
    ],
    "security_findings": [
        {"severity": "warning", "title": "No HSTS", "description": "…", "evidence_header": "Strict-Transport-Security"},
    ],
    "performance_findings": [
        {"severity": "critical", "title": "CDN not caching", "description": "Age flat at 0",
         "evidence_header": "Age"},
    ],
}


class FakeProvider:
    """Returns canned responses in order; records each analyze() call."""

    id = "fake"
    name = "Fake"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def static_models(self) -> list[dict]:
        return []

    async def list_models(self) -> list[dict]:
        return []

    async def analyze(self, *, system, user, model, settings):
        self.calls.append({"system": system, "user": user, "model": model, "settings": settings})
        return self._responses.pop(0)


def _fences(payload: dict) -> str:
    return "```json\n" + json.dumps(payload) + "\n```"


# --- Scenario 1 ---------------------------------------------------------------

async def test_golden_path_parses_serving_layer():
    provider = FakeProvider([json.dumps(VALID_RESULT)])
    result = await run_analysis(AKAMAI_BUNDLE, provider=provider, model="claude-opus-4-8")

    assert isinstance(result, StructuredResult)
    assert result.cache_verdict.serving_layer == "Apache Dispatcher"
    assert result.cache_verdict.cached is False
    assert result.performance_findings[0].severity == "critical"
    assert len(provider.calls) == 1


# --- Scenario 2 ---------------------------------------------------------------

async def test_fenced_response_retried_then_parsed():
    provider = FakeProvider([_fences(VALID_RESULT), json.dumps(VALID_RESULT)])
    result = await run_analysis(AKAMAI_BUNDLE, provider=provider, model="m")

    assert result.cache_verdict.serving_layer == "Apache Dispatcher"
    assert len(provider.calls) == 2  # first fenced -> rejected -> retried
    # The retry carried a correction prefix; the first call did not.
    assert "previous response was not valid JSON" in provider.calls[1]["user"]
    assert "previous response" not in provider.calls[0]["user"]


async def test_leading_prose_rejected_then_parsed():
    prose = "Sure! Here is the analysis:\n" + json.dumps(VALID_RESULT)
    provider = FakeProvider([prose, json.dumps(VALID_RESULT)])
    result = await run_analysis(AKAMAI_BUNDLE, provider=provider, model="m")
    assert isinstance(result, StructuredResult)
    assert len(provider.calls) == 2


# --- Scenario 3 ---------------------------------------------------------------

async def test_two_invalid_responses_raise_parse_error():
    provider = FakeProvider(["not json at all", "still {not json"])
    with pytest.raises(AnalysisParseError) as exc_info:
        await run_analysis(AKAMAI_BUNDLE, provider=provider, model="m")
    assert exc_info.value.attempts == 2
    assert exc_info.value.last_raw == "still {not json"
    assert len(provider.calls) == 2


# --- Scenario 4 ---------------------------------------------------------------

async def test_missing_evidence_headers_triggers_retry():
    broken = json.loads(json.dumps(VALID_RESULT))
    del broken["cache_verdict"]["layers"][0]["evidence_headers"]  # required field
    provider = FakeProvider([json.dumps(broken), json.dumps(VALID_RESULT)])
    result = await run_analysis(AKAMAI_BUNDLE, provider=provider, model="m")
    assert isinstance(result, StructuredResult)
    assert len(provider.calls) == 2


async def test_bad_enum_triggers_retry():
    broken = json.loads(json.dumps(VALID_RESULT))
    broken["cache_verdict"]["layers"][0]["state"] = "hit!"  # invalid enum
    provider = FakeProvider([json.dumps(broken), json.dumps(VALID_RESULT)])
    result = await run_analysis(AKAMAI_BUNDLE, provider=provider, model="m")
    assert isinstance(result, StructuredResult)
    assert len(provider.calls) == 2


async def test_two_schema_violations_raise():
    broken = json.loads(json.dumps(VALID_RESULT))
    broken["cache_verdict"]["layers"][0]["state"] = "nope"
    provider = FakeProvider([json.dumps(broken), json.dumps(broken)])
    with pytest.raises(AnalysisParseError):
        await run_analysis(AKAMAI_BUNDLE, provider=provider, model="m")


# --- Scenario 5 ---------------------------------------------------------------

def test_prompt_contains_constraints_and_vendor_table():
    # The four core §5.3 constraints (verbatim strings).
    assert "must cite evidence that appears verbatim in the input" in SYSTEM_PROMPT
    assert "Do not infer cache layers from traceroute hops." in SYSTEM_PROMPT
    assert "The serving layer is the first layer in the user→origin chain reporting a hit." in SYSTEM_PROMPT
    assert "WAFs and load balancers forward without caching" in SYSTEM_PROMPT
    # Vendor reference table markers.
    for marker in ("CF-Cache-Status", "X-Dispatcher", "edgekey.net", "X-Amz-Cf-Id", "X-Varnish"):
        assert marker in SYSTEM_PROMPT
    # Progression guidance.
    assert "Age flat at 0" in SYSTEM_PROMPT
    assert "CDN bypass" in SYSTEM_PROMPT
    # 1.0.2: non-zero Age is first-class hit evidence, and the verdict must not
    # contradict the narration (multi-CDN inner-cache case; guard against drift).
    assert "non-zero `Age`" in SYSTEM_PROMPT
    assert "Never report `cached: false`" in SYSTEM_PROMPT
    assert "must not contradict your `segment_narration`" in SYSTEM_PROMPT
    assert "an outer CDN often overwrites the inner cache's".lower() in SYSTEM_PROMPT.lower()


# --- Scenario 6 ---------------------------------------------------------------

def _all_keys(obj):
    keys = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.add(key)
            keys |= _all_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _all_keys(item)
    return keys


async def test_payload_audit_and_temp_zero():
    provider = FakeProvider([json.dumps(VALID_RESULT)])
    await run_analysis(AKAMAI_BUNDLE, provider=provider, model="claude-opus-4-8")

    call = provider.calls[0]
    # temp 0 asserted (done-criterion).
    assert call["settings"].temperature == 0
    assert call["system"] == SYSTEM_PROMPT

    # The user message is exactly the bundle as JSON.
    sent = json.loads(call["user"])
    assert sent == AKAMAI_BUNDLE

    # Raw headers of ALL N samples are present.
    samples = sent["samples"]
    assert len(samples) == 4
    for sample in samples:
        assert sample["headers"]  # verbatim [name, value] pairs

    # Enriched hops are present (asn/org).
    assert any(h.get("org") == "Akamai Technologies" for h in sent["traceroute"]["hops"])

    # No pre-computed vendor/hit/miss/layer/verdict fields in the payload (§2).
    forbidden = ("vendor", "hit", "miss", "layer", "verdict")
    offenders = {k for k in _all_keys(sent) if any(f in k.lower() for f in forbidden)}
    assert offenders == set(), offenders


# --- live (excluded by default): real model produces schema-valid JSON --------

@pytest.mark.live
async def test_live_real_model_produces_valid_result():
    import os

    from app.llm.anthropic import AnthropicProvider

    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    result = await run_analysis(
        AKAMAI_BUNDLE, provider=AnthropicProvider(key), model="claude-opus-4-8"
    )
    assert isinstance(result, StructuredResult)
    # The bypass story: Akamai edge with flat Age 0 / no-cache should not be a HIT.
    assert result.cache_verdict.provider  # some provider identified
    assert result.overall_summary
