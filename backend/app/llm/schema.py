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


class Layer(BaseModel):
    layer_name: str
    vendor: str
    cache_type: str
    role: Role
    caches: bool
    state: State
    evidence_headers: list[str]


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
    # Set when the model sent an unusable timing_check (dropped instead of
    # failing the whole verdict); the validator flags it. Never serialized.
    timing_check_error: str | None = Field(default=None, exclude=True)

    @field_validator("confidence_reason", mode="before")
    @classmethod
    def _null_reason(cls, value):
        return "" if value is None else value

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


class StructuredResult(BaseModel):
    """The full §5.2 analysis result. Extra keys from the model are ignored."""

    cache_verdict: CacheVerdict
    overall_summary: str
    segment_narration: list[SegmentNarration]
    security_findings: list[Finding]
    performance_findings: list[Finding]
