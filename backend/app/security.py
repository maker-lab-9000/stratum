"""Security controls (spec §10): an optional basic-auth gate, an optional
outbound allowlist for analysis targets, and a private-range target policy.

All controls are env-driven and OFF by default — Stratum is a trusted-LAN tool,
so a fresh checkout stays open, but an operator can lock it down without code
changes. Secrets are read from the environment here and never persisted.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import os
import secrets
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import Response

HEALTH_PATH = "/api/health"
_TRUTHY = {"1", "true", "yes", "on"}


# --- basic-auth gate ---------------------------------------------------------


def auth_enabled() -> bool:
    return os.getenv("AUTH_ENABLED", "false").strip().lower() in _TRUTHY


def _expected_credentials() -> tuple[str, str]:
    return os.getenv("BASIC_AUTH_USER", ""), os.getenv("BASIC_AUTH_PASS", "")


def _credentials_ok(authorization: str | None) -> bool:
    """Constant-time check of an HTTP Basic ``Authorization`` header."""
    user, password = _expected_credentials()
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    got_user, sep, got_password = decoded.partition(":")
    if not sep:
        return False
    # compare_digest on both fields so a mismatch length doesn't short-circuit.
    return secrets.compare_digest(got_user, user) and secrets.compare_digest(got_password, password)


def add_basic_auth(app: FastAPI) -> None:
    """Gate every route behind HTTP Basic when ``AUTH_ENABLED`` is set.

    ``/api/health`` stays open so container/orchestrator healthchecks work
    without credentials. No-op when auth is disabled.
    """
    if not auth_enabled():
        return

    @app.middleware("http")
    async def _basic_auth_gate(request: Request, call_next):
        if request.url.path == HEALTH_PATH:
            return await call_next(request)
        if _credentials_ok(request.headers.get("authorization")):
            return await call_next(request)
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Stratum"'},
        )


# --- outbound allowlist ------------------------------------------------------


def load_allowlist() -> list[str]:
    """Comma-separated host patterns from ``OUTBOUND_ALLOWLIST`` (empty = allow all).

    Each pattern is an exact host (``api.example.com``) or a wildcard
    (``*.example.com``, which also matches the apex ``example.com``).
    """
    raw = os.getenv("OUTBOUND_ALLOWLIST", "").strip()
    if not raw:
        return []
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def host_matches(host: str, pattern: str) -> bool:
    host = host.lower()
    if pattern.startswith("*."):
        base = pattern[2:]  # "example.com"
        return host == base or host.endswith("." + base)
    return host == pattern


def is_host_allowed(host: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    return any(host_matches(host, p) for p in patterns)


def outbound_rejection_reason(url: str) -> str | None:
    """Return a human-readable reason if ``url``'s host is off the allowlist,
    else ``None`` (allowed). Empty allowlist → always allowed."""
    patterns = load_allowlist()
    if not patterns:
        return None
    host = (urlparse(url).hostname or "").lower()
    if is_host_allowed(host, patterns):
        return None
    return (
        f"target host '{host}' is not in the outbound allowlist "
        f"({', '.join(patterns)}). Set OUTBOUND_ALLOWLIST to permit it."
    )


# --- private-range target policy ---------------------------------------------
# Stratum is a LAN tool, so private/internal targets are ALLOWED by default (an
# operator legitimately points it at homelab hosts). We do not block them; the
# route + resolved addresses are disclosed in the report so an internal target is
# never silently treated as public.


def is_private_target(host: str) -> bool:
    """True when ``host`` is a literal private / loopback / link-local / reserved
    IP. Hostnames are not resolved here (that happens in the DNS stage, whose
    records the report already discloses)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
