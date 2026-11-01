"""T24 — the keyless `fake` LLM provider used by the e2e stack.

It must flow through the real parse (T12) + validate (T13) path and produce a
valid verdict citing real headers, and honour FAKE_LLM_FAIL for the degraded
path — so the compose e2e can run happy + degraded flows without any key.
"""

from __future__ import annotations

import pytest

from app.llm.registry import available_models, build_registry, get_provider
from app.pipeline.analyze import make_llm_analyze

BUNDLE = {
    "meta": {"url": "http://target/", "vantage": "e2e"},
    "samples": [
        {
            "request": 1,
            "headers": [
                ["server", "stratum-e2e-target"],
                ["x-cache", "MISS"],
                ["server-timing", "edge;desc=HIT"],
                ["cache-control", "no-cache"],
                ["age", "0"],
            ],
        },
        {
            "request": 2,
            "headers": [
                ["server", "stratum-e2e-target"],
                ["server-timing", "edge;desc=HIT"],
                ["age", "5"],
            ],
        },
    ],
}


def test_fake_registry_replaces_real_providers(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-be-ignored")
    reg = build_registry()
    assert list(reg) == ["fake"]
    assert available_models()["providers"][0]["id"] == "fake"
    assert get_provider("fake") is not None


async def test_fake_produces_a_validated_verdict(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.delenv("FAKE_LLM_FAIL", raising=False)
    analyze = make_llm_analyze()
    out = await analyze(BUNDLE, "fake", "fake-1")

    verdict = out["verdict_json"]
    assert verdict.get("status") != "unavailable"  # not degraded
    assert verdict["serving_layer"] == "Edge Cache"
    assert verdict["cached"] is True
    # The verdict passed the evidence validator (citations exist in the bundle).
    assert verdict["validation"]["ok"] is True
    assert verdict["validation"]["flags"] == []


async def test_fake_fail_mode_degrades(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("FAKE_LLM_FAIL", "1")
    analyze = make_llm_analyze()
    out = await analyze(BUNDLE, "fake", "fake-1")
    assert out["verdict_json"]["status"] == "unavailable"
    assert out["llm_json"] is None


def test_fake_emits_timing_check():
    import json as _json
    from pathlib import Path as _Path

    from app.llm.fake import _verdict_from_bundle
    from app.llm.schema import StructuredResult
    from app.pipeline.validator import validate_verdict

    bundle = _json.loads((_Path(__file__).parent / "fixtures/bundle/golden_bundle.json").read_text())
    verdict = _verdict_from_bundle(bundle)
    assert verdict["cache_verdict"]["timing_check"]["status"] == "insufficient"
    assert isinstance(verdict["cache_verdict"]["confidence_reason"], str)
    result = validate_verdict(StructuredResult.model_validate(verdict), bundle)
    assert result.ok, result.flags


def test_fake_emits_story_fields():
    import json as _json
    from pathlib import Path as _Path

    from app.llm.fake import _verdict_from_bundle
    from app.llm.schema import StructuredResult
    from app.pipeline.validator import validate_verdict

    bundle = _json.loads((_Path(__file__).parent / "fixtures/bundle/golden_bundle.json").read_text())
    verdict = _verdict_from_bundle(bundle)
    cv = verdict["cache_verdict"]
    assert cv["headline"]
    assert all(layer.get("confidence") for layer in cv["layers"])
    assert cv["layers"][-1]["role"] == "origin"
    result = validate_verdict(StructuredResult.model_validate(verdict), bundle)
    assert result.ok, result.flags
