"""Pydantic models for the LLM's structured output (spec §5.2).

Strict validation is a §2 guardrail: a bad enum (e.g. ``state: "hit!"``) or a
missing required field (e.g. ``evidence_headers``) raises ``ValidationError``,
which the analysis runner treats as an invalid response and retries once.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

Confidence = Literal["high", "medium", "low"]
Role = Literal[
    "client", "edge", "shield", "security",
    "load_balancer", "reverse_proxy", "app_cache", "origin", "unknown",
]
State = Literal["HIT", "MISS", "PASS", "UNKNOWN"]
Severity = Literal["critical", "warning", "info"]
TimingStatus = Literal["consistent", "gap", "insufficient"]
_CONFIDENCES = ("high", "medium", "low")


def _normalize_confidence(value):
    """'High' / ' medium ' → 'high' / 'medium'; other values pass through."""
    return value.strip().lower() if isinstance(value, str) else value


def _optional_confidence(value):
    """1.3.0 per-claim confidence: anything outside the three levels → None
    (unrated), never a parse failure. Case and surrounding spaces are ignored."""
    value = _normalize_confidence(value)
    return value if value in _CONFIDENCES else None


def _blank_if_none(value):
    return "" if value is None else value


class Layer(BaseModel):
    layer_name: str
    vendor: str
    cache_type: str
    role: Role
    caches: bool
    state: State
    evidence_headers: list[str]
    # 1.3.0 — optional, coerced; an unrated layer is None, never a default.
    confidence: Confidence | None = None
    location: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value):
        return _optional_confidence(value)

    @field_validator("location", mode="before")
    @classmethod
    def _location(cls, value):
        return _blank_if_none(value)


class SampleState(BaseModel):
    request: int
    state: State
    evidence_headers: list[str]


class TimingCheck(BaseModel):
    """The LLM's reading of HTTP timing against the header story (1.2.0)."""

    status: TimingStatus
    summary: str = ""
    hidden_layer_suspected: bool = False
    confidence: Confidence = "low"
    evidence: list[str] = []

    @field_validator("summary", mode="before")
    @classmethod
    def _null_summary(cls, value):
        return "" if value is None else value

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence_case(cls, value):
        return _normalize_confidence(value)

    @field_validator("evidence", mode="before")
    @classmethod
    def _null_evidence(cls, value):
        return [] if value is None else value


class CacheVerdict(BaseModel):
    cached: bool
    confidence: Confidence
    provider: str
    provider_evidence: list[str]
    serving_layer: str
    layer_count_to_origin: int
    layers: list[Layer]
    sample_states: list[SampleState]
    # 1.2.0 — optional so a model that omits them never loses the verdict; the
    # validator fills a missing timing_check with an "insufficient" default.
    confidence_reason: str = ""
    timing_check: TimingCheck | None = None
    # 1.3.0 — story fields + provider confidence (optional, coerced).
    headline: str = ""
    headline_detail: str = ""
    provider_confidence: Confidence | None = None
    # Set when the model sent an unusable timing_check (dropped instead of
    # failing the whole verdict); the validator flags it. Never serialized.
    timing_check_error: str | None = Field(default=None, exclude=True)

    @field_validator("confidence_reason", "headline", "headline_detail", mode="before")
    @classmethod
    def _null_text(cls, value):
        return _blank_if_none(value)

    @field_validator("provider_confidence", mode="before")
    @classmethod
    def _provider_conf(cls, value):
        return _optional_confidence(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _verdict_confidence_case(cls, value):
        return _normalize_confidence(value)

    @model_validator(mode="before")
    @classmethod
    def _drop_malformed_timing(cls, data):
        """An invalid timing_check must never cost the verdict (spec anti-goal)."""
        if isinstance(data, dict) and data.get("timing_check") is not None:
            try:
                TimingCheck.model_validate(data["timing_check"])
            except ValidationError:
                data = {**data, "timing_check": None, "timing_check_error": "malformed"}
        return data


class SegmentNarration(BaseModel):
    # segment is spec'd as Access|Transit|CDN network|Origin, but left as a free
    # string so a slightly different phrasing from the model doesn't fail parsing.
    segment: str
    hop_range: str
    description: str
    corroboration: str


class Finding(BaseModel):
    severity: Severity
    title: str
    description: str
    evidence_header: str
    confidence: Confidence | None = None  # 1.3.0

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value):
        return _optional_confidence(value)


class StructuredResult(BaseModel):
    """The full §5.2 analysis result. Extra keys from the model are ignored."""

    cache_verdict: CacheVerdict
    overall_summary: str
    segment_narration: list[SegmentNarration]
    security_findings: list[Finding]
    performance_findings: list[Finding]
