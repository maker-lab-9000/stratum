"""A deterministic, keyless LLM provider for the end-to-end stack (T24).

Selected with ``LLM_PROVIDER=fake``. It reads the evidence bundle from its own
prompt and emits a schema-valid verdict that cites *real* headers from the
captured samples — so it flows through the exact same parse (T12) + validator
(T13) path as a live provider, and the report renders a genuine, validated
verdict without any API key or network call.

``FAKE_LLM_FAIL=1`` makes it return unparseable output, exercising the degraded
path (§5.2) end-to-end.
"""

from __future__ import annotations

import json
import os

from app.llm.base import DEFAULT_SETTINGS, LLMProvider, LLMSettings

_TRUTHY = {"1", "true", "yes", "on"}


class FakeProvider(LLMProvider):
    id = "fake"
    name = "Fake (recorded)"

    def static_models(self) -> list[dict]:
        return [{"id": "fake-1", "name": "Recorded verdict"}]

    async def list_models(self) -> list[dict]:
        return self.static_models()

    async def analyze(
        self, *, system: str, user: str, model: str, settings: LLMSettings = DEFAULT_SETTINGS
    ) -> str:
        # Global fail switch — checked before any parsing.
        if os.getenv("FAKE_LLM_FAIL", "").strip().lower() in _TRUTHY:
            return "the recorded model is unavailable for this run"
        # `user` is the bundle JSON, but a retry attempt prepends correction prose;
        # find the JSON object regardless.
        try:
            bundle = json.loads(user[user.index("{"):])
        except (ValueError, json.JSONDecodeError):
            bundle = {}
        # Per-request fail for any URL carrying the sentinel (lets one e2e stack
        # drive both the happy and degraded flows).
        if "__degrade__" in str(bundle.get("meta", {}).get("url", "")):
            return "the recorded model is unavailable for this run"
        return json.dumps(_verdict_from_bundle(bundle))


def _verdict_from_bundle(bundle: dict) -> dict:
    """Build a valid verdict whose citations are guaranteed to exist in-bundle."""
    samples = bundle.get("samples") or []
    headers: list = samples[0].get("headers", []) if samples else []

    def cite(name: str) -> str | None:
        for pair in headers:
            if len(pair) == 2 and str(pair[0]).lower() == name.lower():
                return f"{pair[0]}: {pair[1]}"
        return None

    first = f"{headers[0][0]}: {headers[0][1]}" if headers else "server: unknown"
    serving = cite("server-timing") or cite("x-cache") or first
    provider = cite("server") or first

    # One serving layer keeps every claim backed by a real citation (the
    # validator flags an empty evidence list even on an UNKNOWN layer).
    layers = [
        {
            "layer_name": "Edge Cache",
            "vendor": "Fake",
            "cache_type": "edge cache",
            "role": "edge",
            "caches": True,
            "state": "HIT",
            "evidence_headers": [serving],
        },
    ]
    sample_states = [
        {"request": s.get("request", i + 1), "state": "HIT", "evidence_headers": [serving]}
        for i, s in enumerate(samples)
    ] or [{"request": 1, "state": "HIT", "evidence_headers": [serving]}]

    return {
        "cache_verdict": {
            "cached": True,
            "confidence": "high",
            "provider": "Fake CDN",
            "provider_evidence": [provider],
            "serving_layer": "Edge Cache",
            "layer_count_to_origin": 1,
            "layers": layers,
            "sample_states": sample_states,
        },
        "overall_summary": "Recorded fake verdict for the e2e stack: served from the edge cache.",
        "segment_narration": [],
        "security_findings": [],
        "performance_findings": [],
    }
