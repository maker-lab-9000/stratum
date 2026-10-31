"""Capture: freeze a finished report from a running Stratum instance into a case.

The report's stored evidence (``dns_json`` / ``samples_json`` /
``traceroute_json``) is copied verbatim. The case starts with no answer key —
the operator fills in ``expected`` by hand when they know the real setup.
Credentials in the link are used for auth and never written to the case file.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
import re
from collections import Counter
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from evals.case import CASES_DIR, NAME_RE, CaseError, parse_case

_ID_PARENTS = {"reports", "runs", "analyses"}
_TIMEOUT_S = 15.0


class CaptureError(Exception):
    """The report can't be fetched or isn't suitable to freeze."""


_USERINFO = re.compile(r"(//)[^/\s]*@")


def _redact(link: str) -> str:
    """The link without any ``user:pass@`` part — safe to print."""
    return _USERINFO.sub(r"\1", link)


def non_2xx_summary(samples: list) -> str | None:
    """``"403×4"``-style status summary when no sample returned 2xx, else None.
    A plain HTTP status class — the evidence may be a block page or redirect."""
    statuses = [s.get("status") for s in samples if isinstance(s, dict) and s.get("ok")]
    if any(isinstance(st, int) and 200 <= st < 300 for st in statuses):
        return None
    counts = Counter(statuses)
    return ", ".join(f"{st}×{n}" for st, n in sorted(counts.items(), key=lambda kv: str(kv[0])))


def parse_report_link(link: str) -> tuple[str, str, tuple[str, str] | None, str]:
    """Return ``(api_url, report_id, userinfo_auth, clean_link)``.

    Accepts ``…/reports/<id>``, ``…/runs/<id>`` or ``…/api/analyses/<id>``.
    ``clean_link`` is the link without userinfo, query, or fragment."""
    parts = urlsplit(link.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise CaptureError(f"not an http(s) report link: {_redact(link)!r}")
    segments = [s for s in parts.path.split("/") if s]
    report_id = None
    for i in range(len(segments) - 2, -1, -1):
        if segments[i] in _ID_PARENTS:
            report_id = segments[i + 1]
            break
    if not report_id:
        raise CaptureError(
            f"can't find a report id in {_redact(link)!r} — expected …/reports/<id>, "
            "…/runs/<id> or …/api/analyses/<id>"
        )
    host = parts.netloc.rsplit("@", 1)[-1]
    auth = None
    if parts.username is not None:
        auth = (unquote(parts.username), unquote(parts.password or ""))
    api_url = f"{parts.scheme}://{host}/api/analyses/{report_id}"
    clean_link = urlunsplit((parts.scheme, host, parts.path, "", ""))
    return api_url, report_id, auth, clean_link


async def fetch_report(link: str, *, env: Mapping[str, str] | None = None) -> tuple[dict, str]:
    """GET the report JSON. Auth: link userinfo, else BASIC_AUTH_USER/PASS."""
    env = env if env is not None else {}
    api_url, _, auth, clean_link = parse_report_link(link)
    if auth is None and env.get("BASIC_AUTH_USER") and env.get("BASIC_AUTH_PASS"):
        auth = (env["BASIC_AUTH_USER"], env["BASIC_AUTH_PASS"])
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            response = await client.get(api_url, auth=httpx.BasicAuth(*auth) if auth else None)
    except httpx.HTTPError as exc:
        raise CaptureError(f"could not reach {api_url} ({type(exc).__name__})") from exc
    if response.status_code == 401:
        raise CaptureError(
            f"{api_url} requires auth — set BASIC_AUTH_USER and BASIC_AUTH_PASS in .env "
            "(or put user:pass@ in the link)"
        )
    if response.status_code == 404:
        raise CaptureError(f"report not found at {api_url}")
    if response.status_code >= 400:
        raise CaptureError(f"{api_url} returned HTTP {response.status_code}")
    try:
        return response.json(), clean_link
    except ValueError as exc:
        raise CaptureError(f"{api_url} did not return JSON") from exc


def build_case(report: dict, *, name: str, link: str, now: datetime) -> dict:
    status = report.get("status")
    if status != "done":
        raise CaptureError(f"report status is {status!r}; only finished ('done') reports can be frozen")
    samples = report.get("samples_json") or []
    if not any(isinstance(s, dict) and s.get("ok") for s in samples):
        raise CaptureError("report has no successful samples — nothing to evaluate")
    verdict = report.get("verdict_json")
    if not isinstance(verdict, dict) or verdict.get("status") == "unavailable":
        verdict = None
    return {
        "name": name,
        "url": report.get("url"),
        "source": {
            "report_link": link,
            "report_id": report.get("id"),
            "captured_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "vantage": report.get("vantage"),
            "provider": report.get("provider"),
            "model": report.get("model"),
        },
        "evidence": {
            "dns": report.get("dns_json"),
            "samples": samples,
            "traceroute": report.get("traceroute_json"),
        },
        "original_verdict": verdict,
        "expected": None,
    }


def write_case(case_data: dict, directory: Path = CASES_DIR) -> Path:
    name = case_data.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise CaptureError(f"case name {name!r} must match {NAME_RE.pattern}")
    path = Path(directory) / f"{name}.json"
    try:
        parse_case(case_data, origin=str(path))
    except CaseError as exc:
        raise CaptureError(str(exc)) from exc
    try:
        with path.open("x", encoding="utf-8") as fh:
            fh.write(json.dumps(case_data, indent=2, ensure_ascii=False) + "\n")
    except FileExistsError as exc:
        raise CaptureError(
            f"{path} already exists — delete it to re-capture (protects a hand-written answer key)"
        ) from exc
    return path


async def capture(
    link: str,
    name: str,
    *,
    directory: Path = CASES_DIR,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> Path:
    if not NAME_RE.match(name or ""):
        raise CaptureError(f"case name {name!r} must match {NAME_RE.pattern}")
    if (Path(directory) / f"{name}.json").exists():
        raise CaptureError(f"{Path(directory) / f'{name}.json'} already exists — delete it to re-capture")
    report, clean_link = await fetch_report(link, env=env)
    case_data = build_case(report, name=name, link=clean_link, now=now or datetime.now(UTC))
    return write_case(case_data, directory)
