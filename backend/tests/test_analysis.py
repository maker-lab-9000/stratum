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
        "confidence_reason": "",
        "timing_check": {"status": "insufficient", "summary": "", "hidden_layer_suspected": False,
                         "confidence": "low", "evidence": []},
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


# --- 1.2.0: timing corroboration ----------------------------------------------

import copy  # noqa: E402


from app.llm.analysis import parse_structured_result  # noqa: E402


def test_parse_with_timing_check():
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["timing_check"] = {
        "status": "gap", "summary": "s", "hidden_layer_suspected": True,
        "confidence": "medium", "evidence": ["edge_rtt_ms: 38.2"],
    }
    data["cache_verdict"]["confidence_reason"] = "r"
    cv = parse_structured_result(json.dumps(data)).cache_verdict
    assert cv.confidence_reason == "r"
    assert cv.timing_check.status == "gap"
    assert cv.timing_check.hidden_layer_suspected is True
    assert cv.timing_check.evidence == ["edge_rtt_ms: 38.2"]
    # A bad status no longer fails the parse (final-review fix: never lose the
    # verdict over the new fields) — the timing_check is dropped and marked.
    data["cache_verdict"]["timing_check"]["status"] = "maybe"
    bad = parse_structured_result(json.dumps(data)).cache_verdict
    assert bad.timing_check is None and bad.timing_check_error == "malformed"


def test_parse_without_new_fields():
    data = copy.deepcopy(VALID_RESULT)
    del data["cache_verdict"]["timing_check"], data["cache_verdict"]["confidence_reason"]
    cv = parse_structured_result(json.dumps(data)).cache_verdict
    assert cv.timing_check is None
    assert cv.confidence_reason == ""


def test_prompt_timing_guidance():
    for marker in ("timing_check", "confidence_reason", "timing.facts", "warm server_ms",
                   "cache_bust", "clearly exceeds the warm spread",
                   "Timing never adds, removes, or re-states layers"):
        assert marker in SYSTEM_PROMPT, marker
    assert "Do not infer cache layers from traceroute hops." in SYSTEM_PROMPT



# (field, value, expected timing_check: "malformed" -> dropped + flagged later,
#  or a dict of attributes the coerced TimingCheck must have)
_MALFORMED = {
    "reason-null": ("confidence_reason", None, None),
    "status-unknown": ("timing_check", {"status": "inconclusive", "summary": "x"}, "malformed"),
    "confidence-unknown": ("timing_check", {"status": "gap", "confidence": "moderate"}, "malformed"),
    "evidence-null": ("timing_check", {"status": "gap", "evidence": None}, {"evidence": []}),
    "summary-null": ("timing_check", {"status": "consistent", "summary": None}, {"summary": ""}),
    "empty-object": ("timing_check", {}, "malformed"),
    "not-an-object": ("timing_check", "gap", "malformed"),
}


@pytest.mark.parametrize("field,value,expected", list(_MALFORMED.values()), ids=list(_MALFORMED))
def test_malformed_new_fields_do_not_lose_verdict(field, value, expected):
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"][field] = value
    cv = parse_structured_result(json.dumps(data)).cache_verdict  # must not raise
    assert isinstance(cv.confidence_reason, str)
    if expected == "malformed":
        assert cv.timing_check is None
        assert cv.timing_check_error == "malformed"
    elif isinstance(expected, dict):
        for attr, want in expected.items():
            assert getattr(cv.timing_check, attr) == want


def test_prompt_probe_header_citation_rule():
    assert "only inside `timing_check` and for the origin layer" in SYSTEM_PROMPT
    assert "cite the probe's headers as plain" in SYSTEM_PROMPT


def test_prompt_real_data_guidance():
    for marker in (
        "PoP or datacenter",                 # location from headers over GeoIP
        "more reliable than GeoIP",
        "WordPress VIP",                     # vendor table row
        "never restate the verdict",         # findings are things to fix or check
        "Vary",                              # cache-key splits
    ):
        assert marker in SYSTEM_PROMPT, marker


# --- 1.3.0: story fields + per-claim confidence --------------------------------

def test_parse_new_story_fields():
    data = copy.deepcopy(VALID_RESULT)
    cv = data["cache_verdict"]
    cv["headline"] = "Served from the Apache Dispatcher."
    cv["headline_detail"] = "Akamai passed every request on."
    cv["provider_confidence"] = "high"
    cv["layers"][0]["confidence"] = "medium"
    cv["layers"][0]["location"] = "Frankfurt"
    data["security_findings"][0]["confidence"] = "low"
    parsed = parse_structured_result(json.dumps(data))
    pv = parsed.cache_verdict
    assert pv.headline == "Served from the Apache Dispatcher."
    assert pv.headline_detail == "Akamai passed every request on."
    assert pv.provider_confidence == "high"
    assert pv.layers[0].confidence == "medium" and pv.layers[0].location == "Frankfurt"
    assert parsed.security_findings[0].confidence == "low"


@pytest.mark.parametrize("bad", ["moderate", "very high", 5, None])
def test_story_fields_optional_and_coerced(bad):
    plain = parse_structured_result(json.dumps(VALID_RESULT))
    pv = plain.cache_verdict
    assert pv.headline == "" and pv.headline_detail == ""
    assert pv.provider_confidence is None
    assert pv.layers[0].confidence is None and pv.layers[0].location == ""
    assert plain.security_findings[0].confidence is None

    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["provider_confidence"] = bad
    data["cache_verdict"]["layers"][0]["confidence"] = bad
    data["performance_findings"][0]["confidence"] = bad
    data["cache_verdict"]["headline"] = None
    data["cache_verdict"]["layers"][0]["location"] = None
    coerced = parse_structured_result(json.dumps(data))  # never raises
    assert coerced.cache_verdict.provider_confidence is None
    assert coerced.cache_verdict.layers[0].confidence is None
    assert coerced.performance_findings[0].confidence is None
    assert coerced.cache_verdict.headline == ""
    assert coerced.cache_verdict.layers[0].location == ""


def test_prompt_story_rules():
    for marker in ("headline", "headline_detail", "provider_confidence", "location",
                   "Always list the origin as the last layer", "at most 100 characters"):
        assert marker in SYSTEM_PROMPT, marker


def test_prompt_summary_order_rule():
    # 1.3.3: the reasoning reads from the user's request down to the origin and
    # ends with the confidence sentence.
    for marker in ("`overall_summary`", "from the request outward", "DNS", "the origin last",
                   "last sentence states the confidence"):
        assert marker in SYSTEM_PROMPT, marker


def test_confidence_values_are_case_insensitive():
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["confidence"] = "High"
    data["cache_verdict"]["provider_confidence"] = " Medium "
    data["cache_verdict"]["layers"][0]["confidence"] = "LOW"
    data["cache_verdict"]["timing_check"] = {"status": "gap", "confidence": "High", "evidence": []}
    data["performance_findings"][0]["confidence"] = "High"
    parsed = parse_structured_result(json.dumps(data))  # must not raise / drop the verdict
    cv = parsed.cache_verdict
    assert cv.confidence == "high"
    assert cv.provider_confidence == "medium"
    assert cv.layers[0].confidence == "low"
    assert cv.timing_check is not None and cv.timing_check.confidence == "high"
    assert parsed.performance_findings[0].confidence == "high"


# --- 1.3.2: hidden cache state ---------------------------------------------------

def test_probe_reached_origin_is_coerced_never_fatal():
    cases = ((True, True), (False, False), ("true", True), ("False", False), (None, None),
             ("maybe", None), (3, None))
    for raw, expected in cases:
        data = copy.deepcopy(VALID_RESULT)
        data["cache_verdict"]["timing_check"] = {
            "status": "consistent", "summary": "s", "hidden_layer_suspected": False,
            "confidence": "high", "evidence": [], "probe_reached_origin": raw,
        }
        tc = StructuredResult.model_validate(data).cache_verdict.timing_check
        assert tc.probe_reached_origin is expected, raw
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["timing_check"] = {"status": "consistent"}
    assert StructuredResult.model_validate(data).cache_verdict.timing_check.probe_reached_origin is None


def test_prompt_hidden_cache_guidance():
    for marker in (
        "milliseconds the edge spent",       # x-timer VE for a Fastly edge in front
        "Fastly-Debug: 1",                   # debug request header ...
        "fastly-debug-ttl",                  # ... and how to read its answer
        "Surrogate-Control",                 # edge TTL kept while Age is reset
        "is not evidence of a miss",         # stripped hit token + Age 0
        "cache_bust differing headers",      # an identical probe proves no miss
        "probe_reached_origin",
        "Custom request headers",            # suggest a debug re-run as a finding
    ):
        assert marker in SYSTEM_PROMPT, marker
    # The forced origin default is gone.
    assert "then `serving_layer` names the origin layer" not in SYSTEM_PROMPT
