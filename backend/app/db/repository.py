"""Repository layer — the ONLY path to the database (spec T02 done-criterion).

Nothing outside this module should build a Session or query ``reports``; the API
(T10) and pipeline (T09) go through these methods so filters, derived columns,
and status handling live in exactly one place.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models import Report

# Fields a caller may set via create()/update(). ``domain`` and ``has_critical``
# are intentionally excluded — they are derived, never caller-supplied.
_WRITABLE_FIELDS = frozenset(
    {
        "url",
        "status",
        "provider",
        "model",
        "vantage",
        "verdict_json",
        "dns_json",
        "traceroute_json",
        "samples_json",
        "llm_json",
        "error",
    }
)


def _domain_of(url: str) -> str:
    """Host portion of the URL, lowercased. Empty string if unparseable."""
    host = urlparse(url).hostname
    return host.lower() if host else ""


def _has_critical(llm_json: Any) -> bool:
    """True if any security/performance finding is severity ``critical``.

    Reads only the LLM output's own ``severity`` field (§5.2) — this is not
    vendor/cache interpretation, so it does not breach the §2 split. Defensive
    against missing keys / malformed shapes.
    """
    if not isinstance(llm_json, dict):
        return False
    for key in ("security_findings", "performance_findings"):
        findings = llm_json.get(key)
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if isinstance(finding, dict) and finding.get("severity") == "critical":
                return True
    return False


class ReportRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(self, *, url: str, **fields: Any) -> Report:
        """Insert a report. Unknown keys raise; derived columns are computed."""
        _reject_unknown_fields(fields)
        report = Report(url=url, **fields)
        report.domain = _domain_of(url)
        report.has_critical = _has_critical(report.llm_json)
        with self._session_factory() as session:
            session.add(report)
            session.commit()
            session.refresh(report)
        return report

    def get(self, report_id: str) -> Report | None:
        with self._session_factory() as session:
            return session.get(Report, report_id)

    def update(self, report_id: str, **fields: Any) -> Report | None:
        """Patch writable fields on an existing report; recompute derived columns.

        Returns the updated report, or None if the id does not exist.
        """
        _reject_unknown_fields(fields)
        with self._session_factory() as session:
            report = session.get(Report, report_id)
            if report is None:
                return None
            for key, value in fields.items():
                setattr(report, key, value)
            if "url" in fields:
                report.domain = _domain_of(report.url)
            if "llm_json" in fields:
                report.has_critical = _has_critical(report.llm_json)
            session.commit()
            session.refresh(report)
            return report

    def list(
        self,
        *,
        domain: str | None = None,
        has_critical: bool | None = None,
        provider: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Report]:
        """History list with the §7 filters, newest first."""
        stmt = select(Report)
        if domain:
            stmt = stmt.where(Report.domain.like(f"%{domain.lower()}%"))
        if has_critical is not None:
            stmt = stmt.where(Report.has_critical.is_(has_critical))
        if provider:
            stmt = stmt.where(Report.provider == provider)
        stmt = stmt.order_by(Report.created_at.desc(), Report.id.desc())
        stmt = stmt.limit(limit).offset(offset)
        with self._session_factory() as session:
            return list(session.scalars(stmt))

    def delete(self, report_id: str) -> bool:
        """Delete by id. Returns True if a row was removed, False if absent."""
        with self._session_factory() as session:
            report = session.get(Report, report_id)
            if report is None:
                return False
            session.delete(report)
            session.commit()
            return True


def _reject_unknown_fields(fields: dict[str, Any]) -> None:
    unknown = set(fields) - _WRITABLE_FIELDS
    if unknown:
        raise ValueError(f"Unknown/derived report fields not writable: {sorted(unknown)}")
