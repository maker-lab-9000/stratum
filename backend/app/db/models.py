"""ORM models. The single table is ``reports`` (spec §6)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Report(Base):
    """One analysis run and its evidence + (later) LLM verdict.

    ``domain`` and ``has_critical`` are denormalized, derived columns that back
    the §7 history filters; they are computed by the repository on write, never
    set by callers. All the nested artifacts are JSON columns (§6).
    """

    __tablename__ = "reports"

    # --- spec §6 columns ---
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    url: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    vantage: Mapped[str | None] = mapped_column(String, nullable=True)
    verdict_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dns_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    traceroute_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    samples_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    llm_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- derived filter columns (§7) ---
    domain: Mapped[str] = mapped_column(String, nullable=False, default="", index=True)
    has_critical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )

    def as_dict(self) -> dict[str, Any]:
        """Plain-dict view for API serialization (spec §7) and test comparisons."""
        return {
            "id": self.id,
            "url": self.url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "vantage": self.vantage,
            "verdict_json": self.verdict_json,
            "dns_json": self.dns_json,
            "traceroute_json": self.traceroute_json,
            "samples_json": self.samples_json,
            "llm_json": self.llm_json,
            "error": self.error,
            "domain": self.domain,
            "has_critical": self.has_critical,
        }
