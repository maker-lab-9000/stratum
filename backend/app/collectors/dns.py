"""DNS resolver (spec §3.1) — deterministic evidence only.

Returns the raw facts the LLM later interprets: A/AAAA addresses, the full
ordered CNAME chain, authoritative NS, and a representative record TTL. This
module makes no claim about vendors or providers — a CNAME target like
``edgekey.net`` is captured verbatim; the *meaning* is the LLM's job (§2, §4.5).

Testability: all network access goes through the ``Querier`` protocol. The
default ``DnspythonQuerier`` wraps dnspython's async resolver; tests inject a
fake querier so no live DNS is needed (dnspython exceptions never leak — they
are translated to the typed ``DnsError`` hierarchy below).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

# Guard against CNAME loops / pathological chains (spec §3.1 scenario 5).
MAX_CNAME_HOPS = 10
DEFAULT_TIMEOUT_S = 5.0


# --- typed errors -------------------------------------------------------------

class DnsError(Exception):
    """Base for typed DNS failures. Deterministic code raises these, never
    lets a resolver-library exception escape (spec §3.1 scenario 3)."""


class DnsNXDomain(DnsError):
    def __init__(self, name: str) -> None:
        super().__init__(f"NXDOMAIN: {name}")
        self.name = name


class DnsNoAnswer(DnsError):
    """NODATA — the name exists but has no record of the requested type.
    Used internally as a control signal (no CNAME / no A / no AAAA)."""

    def __init__(self, name: str, rdtype: str | None = None) -> None:
        super().__init__(f"No {rdtype or 'record'} for {name}")
        self.name = name
        self.rdtype = rdtype


class DnsResolutionError(DnsError):
    """Timeout, no reachable nameservers, or any other resolution failure."""


# --- query abstraction --------------------------------------------------------

@dataclass
class QueryAnswer:
    """A resolved rrset: record texts (verbatim) + the rrset TTL."""

    records: list[str]
    ttl: int | None


class Querier(Protocol):
    async def query(self, name: str, rdtype: str) -> QueryAnswer:
        """Resolve one (name, rdtype). Raise DnsNXDomain / DnsNoAnswer /
        DnsResolutionError — never a library-specific exception."""
        ...


class DnspythonQuerier:
    """Default querier backed by dnspython's async resolver."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_S, resolver=None) -> None:
        import dns.asyncresolver

        self._resolver = resolver or dns.asyncresolver.Resolver()
        self._resolver.lifetime = timeout

    async def query(self, name: str, rdtype: str) -> QueryAnswer:
        import dns.exception
        import dns.resolver

        try:
            answer = await self._resolver.resolve(name, rdtype, raise_on_no_answer=True)
        except dns.resolver.NXDOMAIN as exc:
            raise DnsNXDomain(name) from exc
        except dns.resolver.NoAnswer as exc:
            raise DnsNoAnswer(name, rdtype) from exc
        except (dns.resolver.NoNameservers, dns.exception.Timeout) as exc:
            raise DnsResolutionError(f"{type(exc).__name__} resolving {rdtype} {name}") from exc
        except dns.exception.DNSException as exc:  # catch-all: no library leak
            raise DnsResolutionError(f"{type(exc).__name__} resolving {rdtype} {name}") from exc

        records = [rdata.to_text() for rdata in answer]
        ttl = answer.rrset.ttl if answer.rrset is not None else None
        return QueryAnswer(records=records, ttl=ttl)


# --- resolution ---------------------------------------------------------------

async def resolve_dns(target: str, *, querier: Querier | None = None) -> dict:
    """Resolve ``target`` (hostname or URL) to a JSON-serializable DNS fact bundle.

    Shape (serializes directly into ``dns_json``, spec §6):
        {
          "a": [str, ...],
          "aaaa": [str, ...],
          "cname_chain": [{"name": str, "cname": str, "ttl": int|None}, ...],
          "ns": [str, ...],
          "ttl": int | None,      # A ttl, else AAAA ttl, else last CNAME ttl
          "truncated": bool,      # CNAME loop or >MAX_CNAME_HOPS hit
        }

    Raises DnsNXDomain if the name does not exist (pipeline marks the stage
    failed, §3.1 scenario 3).
    """
    if querier is None:
        querier = DnspythonQuerier()

    hostname = _hostname(target)
    cname_chain, canonical, truncated = await _walk_cname_chain(querier, hostname)

    a, a_ttl = await _resolve_addresses(querier, canonical, "A")
    aaaa, aaaa_ttl = await _resolve_addresses(querier, canonical, "AAAA")
    ns = await _resolve_ns(querier, hostname)

    if a:
        ttl = a_ttl
    elif aaaa:
        ttl = aaaa_ttl
    elif cname_chain:
        ttl = cname_chain[-1]["ttl"]
    else:
        ttl = None

    return {
        "a": a,
        "aaaa": aaaa,
        "cname_chain": cname_chain,
        "ns": ns,
        "ttl": ttl,
        "truncated": truncated,
    }


async def _walk_cname_chain(
    querier: Querier, hostname: str
) -> tuple[list[dict], str, bool]:
    """Follow CNAMEs from ``hostname`` to the canonical name, in order.

    Returns (chain, canonical_name, truncated). ``truncated`` is True on a loop
    or when MAX_CNAME_HOPS is exhausted while a CNAME still points onward.
    NXDOMAIN propagates (the name itself does not exist).
    """
    chain: list[dict] = []
    seen = {hostname}
    current = hostname
    truncated = False

    for _ in range(MAX_CNAME_HOPS):
        try:
            answer = await querier.query(current, "CNAME")
        except DnsNoAnswer:
            break  # no CNAME here → current is the canonical name
        target = _normalize(answer.records[0]) if answer.records else ""
        chain.append({"name": current, "cname": target, "ttl": answer.ttl})
        if not target or target in seen:
            truncated = True  # loop or empty target: stop, flag it
            break
        seen.add(target)
        current = target
    else:
        # Loop completed without break → a CNAME still points onward.
        truncated = True

    return chain, current, truncated


async def _resolve_addresses(
    querier: Querier, name: str, rdtype: str
) -> tuple[list[str], int | None]:
    """A/AAAA lookup; NODATA → empty list (e.g. AAAA-only or A-only hosts)."""
    try:
        answer = await querier.query(name, rdtype)
    except DnsNoAnswer:
        return [], None
    return [_normalize(r) for r in answer.records], answer.ttl


async def _resolve_ns(querier: Querier, hostname: str) -> list[str]:
    """Authoritative NS, best-effort: query the name, walking up labels until an
    NS rrset is found. Supplementary evidence — never fails the whole resolve."""
    name = hostname
    while "." in name:
        try:
            answer = await querier.query(name, "NS")
            return [_normalize(r) for r in answer.records]
        except DnsError:
            # NODATA / NXDOMAIN / resolution issue at this level → try parent.
            name = name.split(".", 1)[1]
    return []


# --- helpers ------------------------------------------------------------------

def _hostname(target: str) -> str:
    """Extract a bare hostname from a URL or host string."""
    value = target.strip()
    if "://" in value:
        value = urlparse(value).hostname or ""
    elif "/" in value:
        value = value.split("/", 1)[0]
    return _normalize(value)


def _normalize(name: str) -> str:
    """Lowercase and drop the trailing root dot for readable, comparable names."""
    return name.strip().rstrip(".").lower()
