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
    forbidden = [
        "akamai", "cloudflare", "fastly", "cloudfront", "varnish", "dispatcher",
        "nginx", "x-cache", "cf-ray", "cf-cache-status", "x-served-by",
        "x-dispatcher", "x-amz-cf-id", "x-varnish", "x-cache-status", "edgekey",
        "akamaiedge", "cloudfront", "server-timing",
    ]
    present = [token for token in forbidden if token in source]
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
