"""T13 — evidence validator (spec §2 guardrails, §5.2).

Scenarios:
  1. All citations present -> verdict unchanged, no flags.
  2. Fabricated header never captured -> that layer's state -> UNKNOWN + flag.
  3. CNAME citation matches dns_json; ASN citation matches enriched hops.
  4. Case/format tolerance: cited value is a substring of a captured value.
  5. Vendor-agnosticism: validator source has NO vendor names / header allowlist.
  6. Serving-layer cascade: its evidence fails -> confidence low + serving_layer flag.

Vendor-agnosticism note (§5 scenario 5): app/pipeline/validator.py must contain
no vendor names and no hardcoded header allowlist — matching is built only from
the captured evidence at runtime. test_no_vendor_names_in_source enforces this.
"""

import copy
import json
from pathlib import Path

from app.llm.schema import StructuredResult
from app.pipeline.validator import _EvidenceIndex, validate_verdict
from tests.test_analysis import VALID_RESULT
from tests.vendor_tokens import FORBIDDEN_VENDOR_TOKENS

BUNDLE = json.loads(
    (Path(__file__).parent / "fixtures" / "bundle" / "golden_bundle.json").read_text()
)


def _result(payload: dict) -> StructuredResult:
    return StructuredResult.model_validate(payload)


# --- Scenario 1 ---------------------------------------------------------------

def test_all_citations_present_no_flags():
    # VALID_RESULT cites Server: AkamaiGHost / X-Cache: TCP_MISS from a23-fra /
    # the edgekey CNAME / Via — all present in the golden bundle.
    result = validate_verdict(_result(VALID_RESULT), BUNDLE)
    assert result.ok is True
    assert result.flags == []
    assert result.verdict.cache_verdict.layers[0].state == "PASS"  # unchanged
    assert result.verdict.cache_verdict.provider == "Akamai"


# --- Scenario 2 ---------------------------------------------------------------

def test_fabricated_header_downgrades_layer_state():
    payload = copy.deepcopy(VALID_RESULT)
    payload["cache_verdict"]["layers"][0]["evidence_headers"] = ["X-Cache: TCP_HIT from never-seen"]
    result = validate_verdict(_result(payload), BUNDLE)

    assert result.verdict.cache_verdict.layers[0].state == "UNKNOWN"
    assert not result.ok
    flag = next(f for f in result.flags if f.path == "cache_verdict.layers[0].state")
    assert flag.citation == "X-Cache: TCP_HIT from never-seen"


# --- Scenario 3 ---------------------------------------------------------------

def test_cname_and_asn_citations_match():
    index = _EvidenceIndex(BUNDLE)
    # CNAME fragment present in dns_json cname_chain.
    assert index.contains("edgekey.net") is True
    # ASN citation matches the enriched hop's integer asn (20940).
    assert index.contains("AS20940 Akamai Technologies") is True
    assert index.contains("AS20940") is True
    # Org string substring also matches.
    assert index.contains("Akamai Technologies") is True
    # A genuinely absent ASN does not match.
    assert index.contains("AS64500 Nowhere") is False


# --- Scenario 4 ---------------------------------------------------------------

def test_case_and_substring_tolerance():
    index = _EvidenceIndex(BUNDLE)
    # Captured header is `X-Cache: TCP_MISS from a23-fra` — cited shorter value
    # + different name case still matches.
    assert index.contains("x-cache: TCP_MISS from a23") is True
    # Bare header name (any case) matches.
    assert index.contains("Cache-Control") is True
    # Fabricated value under a real header name does NOT match.
    assert index.contains("X-Cache: TCP_HIT") is False


def test_descriptive_citations_from_real_models():
    # Real models cite evidence descriptively; the validator must not
    # false-negative on these (regression: a live opus-4-8 run produced them).
    index = _EvidenceIndex(BUNDLE)
    assert index.contains("traceroute hop 2 org: Akamai Technologies") is True
    assert index.contains("CNAME www.example-foods.com → example-foods.com.edgekey.net") is True
    assert index.contains("Server: AkamaiGHost (Age: 0 across all samples)") is True
    # A descriptive citation referencing NO captured value fails. (Documented
    # tolerance: a citation that wraps a real hostname/org — even with a false
    # target — is accepted as "some cited evidence exists"; strictness is the
    # LLM's job, existence is the validator's.)
    assert index.contains("CNAME fake-host.invalid → made-up.fake-cdn.net") is False
    assert index.contains("traceroute hop 9 org: Nonexistent Networks Inc") is False


# --- Scenario 5 ---------------------------------------------------------------

def test_no_vendor_names_in_source():
    source = (
        Path(__file__).resolve().parents[1] / "app" / "pipeline" / "validator.py"
    ).read_text().lower()
    present = [token for token in FORBIDDEN_VENDOR_TOKENS if token in source]
    assert present == [], f"vendor/header signatures leaked into the validator: {present}"


# --- Scenario 6 ---------------------------------------------------------------

def test_serving_layer_cascade_lowers_confidence():
    payload = copy.deepcopy(VALID_RESULT)
    # serving_layer == "Apache Dispatcher" is layers[1]; break its evidence.
    assert payload["cache_verdict"]["serving_layer"] == "Apache Dispatcher"
    payload["cache_verdict"]["layers"][1]["evidence_headers"] = ["Server: totally-fabricated"]
    result = validate_verdict(_result(payload), BUNDLE)

    cv = result.verdict.cache_verdict
    assert cv.layers[1].state == "UNKNOWN"
    assert cv.confidence == "low"  # documented cascade
    assert any(f.path == "cache_verdict.serving_layer" for f in result.flags)


# --- extra: provider + findings downgrade + report shape ----------------------

def test_provider_evidence_failure_downgrades_provider():
    payload = copy.deepcopy(VALID_RESULT)
    payload["cache_verdict"]["provider_evidence"] = ["invented.cdn.example"]
    result = validate_verdict(_result(payload), BUNDLE)
    assert result.verdict.cache_verdict.provider == "UNKNOWN"
    assert any(f.path == "cache_verdict.provider" for f in result.flags)


def test_finding_with_bad_evidence_is_flagged_not_removed():
    payload = copy.deepcopy(VALID_RESULT)
    payload["security_findings"][0]["evidence_header"] = "X-Made-Up-Header: nope"
    result = validate_verdict(_result(payload), BUNDLE)
    # Finding kept...
    assert len(result.verdict.security_findings) == 1
    # ...but flagged unverified.
    assert any(f.path == "security_findings[0].evidence_header" for f in result.flags)


def test_verdict_json_embeds_validation_report():
    result = validate_verdict(_result(VALID_RESULT), BUNDLE)
    vj = result.verdict_json()
    assert vj["provider"] == "Akamai"
    assert vj["validation"] == {"ok": True, "flags": []}
    # Serializable.
    assert json.loads(json.dumps(vj)) == vj


# --- 1.2.0: timing citations, probe exclusion, honest headline -----------------

from app.pipeline.validator import DISCARDED_SUMMARY, NOTE_SERVING, NOTE_TIMING  # noqa: E402

_FACTS = ["edge_rtt_ms: 38.2", "request 2 server_ms: 3.2", "cache_bust server_ms: 412.5"]


def _timed_bundle() -> dict:
    bundle = copy.deepcopy(BUNDLE)
    bundle["timing"] = {"edge_rtt_ms": 38.2, "requests": [], "cache_bust": None, "facts": list(_FACTS)}
    probe = copy.deepcopy(bundle["samples"][0])
    probe.update({"request": 5, "probe": "cache_bust",
                  "headers": probe["headers"] + [["x-probe-only", "abc123"]]})
    bundle["samples"].append(probe)
    return bundle


def _with_timing(evidence, status="gap", reason="timing disagrees"):
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["confidence_reason"] = reason
    data["cache_verdict"]["timing_check"] = {
        "status": status, "summary": "s", "hidden_layer_suspected": True,
        "confidence": "medium", "evidence": evidence,
    }
    return StructuredResult.model_validate(data)


def _timing_flags(result):
    return [f for f in result.flags if f.path == "cache_verdict.timing_check"]


def test_probe_headers_not_claim_evidence():
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["layers"][0]["evidence_headers"] = ["x-probe-only: abc123"]
    result = validate_verdict(StructuredResult.model_validate(data), _timed_bundle())
    assert result.verdict.cache_verdict.layers[0].state == "UNKNOWN"
    flag = next(f for f in result.flags if f.path == "cache_verdict.layers[0].state")
    # Final review fix: the reason says where the header actually is.
    assert flag.reason == "cited header appears only on the cache-bust probe"


def test_timing_check_valid_citations():
    result = validate_verdict(_with_timing(["edge_rtt_ms: 38.2", "x-probe-only: abc123"]), _timed_bundle())
    tc = result.verdict.cache_verdict.timing_check
    assert tc.status == "gap" and tc.hidden_layer_suspected is True
    assert _timing_flags(result) == []


def test_timing_citation_must_be_exact_fact():
    result = validate_verdict(_with_timing(["edge_rtt_ms: 38.2", "request 2 server_ms: 412.5"]),
                              _timed_bundle())
    cv = result.verdict.cache_verdict
    assert cv.timing_check.status == "insufficient"
    assert cv.timing_check.hidden_layer_suspected is False
    assert _timing_flags(result)
    assert cv.confidence_reason.endswith(NOTE_TIMING)
    # Final review fix: a discarded assessment no longer shows its claims.
    assert cv.timing_check.summary == DISCARDED_SUMMARY
    assert cv.timing_check.confidence == "low"
    assert cv.timing_check.evidence == []


def test_timing_check_without_any_fact_fails():
    result = validate_verdict(_with_timing(["x-probe-only: abc123"]), _timed_bundle())
    assert result.verdict.cache_verdict.timing_check.status == "insufficient"
    assert _timing_flags(result)


def test_insufficient_timing_check_needs_no_evidence():
    result = validate_verdict(_with_timing([], status="insufficient", reason=""), _timed_bundle())
    assert result.verdict.cache_verdict.timing_check.status == "insufficient"
    assert _timing_flags(result) == []
    assert result.verdict.cache_verdict.confidence_reason == ""


def test_missing_timing_check_defaults_and_flags():
    data = copy.deepcopy(VALID_RESULT)
    del data["cache_verdict"]["timing_check"]
    data["cache_verdict"]["confidence_reason"] = "as reported"
    result = validate_verdict(StructuredResult.model_validate(data), _timed_bundle())
    cv = result.verdict.cache_verdict
    assert cv.timing_check.status == "insufficient"
    assert [f.reason for f in _timing_flags(result)] == ["not provided"]
    assert cv.confidence_reason == "as reported"
    assert result.verdict_json()["timing_check"]["status"] == "insufficient"


def test_serving_cascade_appends_note():
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["confidence_reason"] = "model reason"
    data["cache_verdict"]["layers"][1]["evidence_headers"] = ["X-Fabricated: nope"]
    result = validate_verdict(StructuredResult.model_validate(data), _timed_bundle())
    cv = result.verdict.cache_verdict
    assert cv.confidence == "low"
    assert cv.confidence_reason == "model reason" + NOTE_SERVING



def test_fact_shape_catches_hyphenated_fabrication():
    # Loose rule 6 would accept this (it wraps a captured X-Cache value); any
    # "<x>_ms: <number>" citation must be an exact fact.
    citation = "cache-bust server_ms: 999.9 (X-Cache: TCP_MISS from a23-fra)"
    result = validate_verdict(_with_timing(["edge_rtt_ms: 38.2", citation]), _timed_bundle())
    assert result.verdict.cache_verdict.timing_check.status == "insufficient"
    assert any(f.citation == citation for f in _timing_flags(result))


def test_plain_probe_header_citation_accepted_in_timing_check():
    result = validate_verdict(_with_timing(["cache_bust server_ms: 412.5", "Age: 0"]), _timed_bundle())
    assert result.verdict.cache_verdict.timing_check.status == "gap"
    assert _timing_flags(result) == []


def test_malformed_timing_check_flagged_as_malformed():
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["timing_check"] = {"status": "inconclusive"}
    result = validate_verdict(StructuredResult.model_validate(data), _timed_bundle())
    assert result.verdict.cache_verdict.timing_check.status == "insufficient"
    assert [f.reason for f in _timing_flags(result)] == ["malformed"]
    assert "timing_check_error" not in result.verdict_json()


# --- 1.3.0: failed citations force per-claim confidence to low -----------------

def test_failed_layer_citation_sets_low_confidence():
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["layers"][1]["evidence_headers"] = ["X-Fabricated: nope"]
    data["cache_verdict"]["layers"][1]["confidence"] = "high"
    layer = validate_verdict(StructuredResult.model_validate(data), BUNDLE).verdict.cache_verdict.layers[1]
    assert layer.state == "UNKNOWN"
    assert layer.confidence == "low"


def test_failed_provider_evidence_sets_low_confidence():
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["provider_evidence"] = ["X-Fabricated: nope"]
    data["cache_verdict"]["provider_confidence"] = "high"
    cv = validate_verdict(StructuredResult.model_validate(data), BUNDLE).verdict.cache_verdict
    assert cv.provider == "UNKNOWN"
    assert cv.provider_confidence == "low"


def test_failed_finding_citation_sets_low_confidence():
    data = copy.deepcopy(VALID_RESULT)
    data["performance_findings"][0].update({"evidence_header": "X-Fake: nope", "confidence": "high"})
    data["security_findings"][0]["confidence"] = "high"  # bare-name absence finding
    result = validate_verdict(StructuredResult.model_validate(data), BUNDLE)
    assert any(f.path == "performance_findings[0].evidence_header" for f in result.flags)
    assert result.verdict.performance_findings[0].confidence == "low"
    assert result.verdict.security_findings[0].confidence == "high"



# --- 1.3.1: the origin layer may cite the cache-bust probe ----------------------

def test_origin_layer_may_cite_probe_headers():
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["layers"].append({
        "layer_name": "Origin", "vendor": "v", "cache_type": "origin", "role": "origin", "caches": False,
        "state": "UNKNOWN", "evidence_headers": ["x-probe-only: abc123"], "confidence": "medium",
    })
    result = validate_verdict(StructuredResult.model_validate(data), _timed_bundle())
    origin = result.verdict.cache_verdict.layers[-1]
    assert origin.confidence == "medium"
    assert not any(f.path == "cache_verdict.layers[2].state" for f in result.flags)


def test_non_origin_layer_still_cannot_cite_probe_headers():
    data = copy.deepcopy(VALID_RESULT)
    data["cache_verdict"]["layers"][0]["evidence_headers"] = ["x-probe-only: abc123"]
    result = validate_verdict(StructuredResult.model_validate(data), _timed_bundle())
    flag = next(f for f in result.flags if f.path == "cache_verdict.layers[0].state")
    assert flag.reason == "cited header appears only on the cache-bust probe"
