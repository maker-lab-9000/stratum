"""Pydantic models for the LLM's structured output (spec §5.2).

Strict validation is a §2 guardrail: a bad enum (e.g. ``state: "hit!"``) or a
missing required field (e.g. ``evidence_headers``) raises ``ValidationError``,
which the analysis runner treats as an invalid response and retries once.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Confidence = Literal["high", "medium", "low"]
Role = Literal[
    "client", "edge", "shield", "security",
    "load_balancer", "reverse_proxy", "app_cache", "origin", "unknown",
]
State = Literal["HIT", "MISS", "PASS", "UNKNOWN"]
Severity = Literal["critical", "warning", "info"]


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


class CacheVerdict(BaseModel):
    cached: bool
    confidence: Confidence
    provider: str
    provider_evidence: list[str]
    serving_layer: str
    layer_count_to_origin: int
    layers: list[Layer]
    sample_states: list[SampleState]


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
