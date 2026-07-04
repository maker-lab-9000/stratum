"""Request/response models for the analysis API (spec §7)."""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class AnalysisOptions(BaseModel):
    """§7 options block. Bounds keep an operator from launching pathological runs."""

    request_count: int = Field(default=4, ge=1, le=20)
    interval_ms: int = Field(default=0, ge=0, le=60_000)
    warm: bool = True
    extra_request_headers: dict[str, str] = Field(default_factory=dict)
    geo_hint: str | None = None


class CreateAnalysisRequest(BaseModel):
    url: str
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)

    @field_validator("url")
    @classmethod
    def _absolute_http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        return value


class CreateAnalysisResponse(BaseModel):
    id: str
