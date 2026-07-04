"""Network enrichment (spec §3.4, §4.4) — deterministic evidence only.

Enriches each traceroute hop with reverse-DNS, MaxMind GeoLite2 ASN/org + city,
and an airport-code geo *hint* parsed from the rDNS name. All facts, no
interpretation: an ASN org string like "Akamai Technologies" is captured, not
labeled as "the CDN" — the LLM decides what it means (§2, §4.5).

Design goals from the spec:
- Offline by default: MaxMind is a local .mmdb; no per-hop external API calls.
- Graceful degradation: with no MaxMind DB, ASN/geo become ``"unknown"`` and a
  note is emitted — the rest of the pipeline is unaffected.
- The airport-code hint (``fra``/``ffm`` -> Frankfurt) is a *hint* field, kept
  distinct from the authoritative MaxMind city.

All I/O (rDNS, MaxMind, Team-Cymru fallback) is behind small injectable
interfaces so tests need no live network or real databases.
"""

from __future__ import annotations

import ipaddress
import re
import tarfile
from io import BytesIO
from pathlib import Path
from typing import Protocol

import maxminddb

REVERSE_TIMEOUT_S = 2.0

_DEGRADED_NOTE = (
    "MaxMind GeoLite2 ASN/City database unavailable; ASN/geo shown as 'unknown'. "
    "Set MAXMIND_LICENSE_KEY to download the offline databases (spec §3.4, §9.1)."
)


class EnrichmentConfigError(Exception):
    """Configuration problem (e.g. MaxMind download requested with no key)."""


# --- airport / city geo hints -------------------------------------------------
# Router names embed location codes (IATA airports + common carrier abbrevs).
# This is a GEO reference, not a cache-vendor signature — allowed by §2.
_LOCATION_HINTS: dict[str, tuple[str, str]] = {
    "fra": ("FRA", "Frankfurt"), "ffm": ("FRA", "Frankfurt"),
    "ams": ("AMS", "Amsterdam"),
    "lhr": ("LHR", "London"), "lon": ("LHR", "London"), "ldn": ("LHR", "London"),
    "cdg": ("CDG", "Paris"), "par": ("CDG", "Paris"),
    "iad": ("IAD", "Ashburn"), "ash": ("IAD", "Ashburn"),
    "jfk": ("JFK", "New York"), "nyc": ("JFK", "New York"), "ewr": ("EWR", "Newark"),
    "lax": ("LAX", "Los Angeles"),
    "sjc": ("SJC", "San Jose"), "sfo": ("SFO", "San Francisco"),
    "dfw": ("DFW", "Dallas"), "ord": ("ORD", "Chicago"), "chi": ("ORD", "Chicago"),
    "sea": ("SEA", "Seattle"), "atl": ("ATL", "Atlanta"), "mia": ("MIA", "Miami"),
    "sin": ("SIN", "Singapore"),
    "nrt": ("NRT", "Tokyo"), "hnd": ("HND", "Tokyo"), "tyo": ("NRT", "Tokyo"),
    "hkg": ("HKG", "Hong Kong"), "syd": ("SYD", "Sydney"),
    "mad": ("MAD", "Madrid"), "mrs": ("MRS", "Marseille"), "muc": ("MUC", "Munich"),
    "ber": ("BER", "Berlin"), "dus": ("DUS", "Dusseldorf"), "ham": ("HAM", "Hamburg"),
    "vie": ("VIE", "Vienna"), "zrh": ("ZRH", "Zurich"),
    "mil": ("MXP", "Milan"), "mxp": ("MXP", "Milan"),
    "waw": ("WAW", "Warsaw"), "arn": ("ARN", "Stockholm"), "sto": ("ARN", "Stockholm"),
    "dub": ("DUB", "Dublin"),
}


def airport_hint(rdns: str | None) -> str | None:
    """Return a ``"CODE/City"`` geo hint parsed from an rDNS name, or None.

    Matches whole dot/dash/underscore-separated tokens, also trying the token
    with trailing digits stripped (``fra1`` -> ``fra``)."""
    if not rdns:
        return None
    for raw in re.split(r"[.\-_]", rdns.lower()):
        for token in (raw, re.sub(r"\d+$", "", raw)):
            if token in _LOCATION_HINTS:
                code, city = _LOCATION_HINTS[token]
                return f"{code}/{city}"
    return None


# --- reverse DNS --------------------------------------------------------------

class ReverseResolver(Protocol):
    async def reverse(self, ip: str) -> str | None:
        """PTR lookup. Return the hostname, or None on NODATA/timeout/failure."""
        ...


class DnspythonReverseResolver:
    def __init__(self, timeout: float = REVERSE_TIMEOUT_S, resolver=None) -> None:
        import dns.asyncresolver

        self._resolver = resolver or dns.asyncresolver.Resolver()
        self._resolver.lifetime = timeout

    async def reverse(self, ip: str) -> str | None:
        import dns.exception
        import dns.resolver
        import dns.reversename

        try:
            rev_name = dns.reversename.from_address(ip)
            answer = await self._resolver.resolve(rev_name, "PTR")
        except dns.exception.DNSException:
            return None  # NXDOMAIN / NoAnswer / Timeout / etc.
        return str(answer[0]).rstrip(".").lower()


# --- ASN + city providers -----------------------------------------------------

class GeoProvider(Protocol):
    asn_available: bool
    city_available: bool

    def lookup_asn(self, ip: str) -> tuple[int | None, str | None]: ...
    def lookup_city(self, ip: str) -> str | None: ...


class NullGeoProvider:
    """No databases — everything degrades to unavailable."""

    asn_available = False
    city_available = False

    def lookup_asn(self, ip: str) -> tuple[int | None, str | None]:
        return (None, None)

    def lookup_city(self, ip: str) -> str | None:
        return None


class MaxMindGeoProvider:
    """Reads GeoLite2-ASN / GeoLite2-City .mmdb files via maxminddb (offline)."""

    def __init__(self, asn_db_path: str | None = None, city_db_path: str | None = None) -> None:
        self._asn = self._open(asn_db_path)
        self._city = self._open(city_db_path)

    @staticmethod
    def _open(path: str | None):
        if path and Path(path).exists():
            return maxminddb.open_database(path)
        return None

    @property
    def asn_available(self) -> bool:
        return self._asn is not None

    @property
    def city_available(self) -> bool:
        return self._city is not None

    def lookup_asn(self, ip: str) -> tuple[int | None, str | None]:
        if self._asn is None:
            return (None, None)
        record = self._asn.get(ip)
        if not record:
            return (None, None)
        return (
            record.get("autonomous_system_number"),
            record.get("autonomous_system_organization"),
        )

    def lookup_city(self, ip: str) -> str | None:
        if self._city is None:
            return None
        record = self._city.get(ip)
        if not record:
            return None
        return record.get("city", {}).get("names", {}).get("en")


class CymruAsnFallback:
    """Team-Cymru DNS-whois ASN fallback (spec §3.4). Opt-in only — it makes
    external DNS queries, so it is NOT wired into the default offline path.
    IPv4 only; IPv6 returns (None, None)."""

    def __init__(self, txt_query) -> None:
        # txt_query: async callable(name: str) -> list[str]
        self._txt = txt_query

    async def lookup_asn(self, ip: str) -> tuple[int | None, str | None]:
        try:
            if ipaddress.ip_address(ip).version != 4:
                return (None, None)
        except ValueError:
            return (None, None)
        reversed_ip = ".".join(reversed(ip.split(".")))
        origin = await self._txt(f"{reversed_ip}.origin.asn.cymru.com")
        if not origin:
            return (None, None)
        asn_field = origin[0].split("|")[0].strip().split()
        if not asn_field:
            return (None, None)
        asn = int(asn_field[0])
        org = None
        as_txt = await self._txt(f"AS{asn}.asn.cymru.com")
        if as_txt:
            org = as_txt[0].split("|")[-1].strip() or None
        return (asn, org)


# --- enrichment ---------------------------------------------------------------

async def enrich_hops(
    hops: list[dict],
    *,
    geo: GeoProvider | None = None,
    reverse_resolver: ReverseResolver | None = None,
    asn_fallback=None,
) -> dict:
    """Enrich normalized traceroute hops. Returns:

        {"hops": [ {n, ip, rdns, asn, org, city, rtt_ms, private, unresponsive,
                    hint}, ... ],
         "geo_available": bool,
         "notes": [str, ...]}
    """
    geo = geo if geo is not None else NullGeoProvider()
    enriched = [
        await _enrich_one(hop, geo, reverse_resolver, asn_fallback) for hop in hops
    ]

    geo_available = geo.asn_available or geo.city_available
    notes: list[str] = []
    if not (geo.asn_available and geo.city_available):
        notes.append(_DEGRADED_NOTE)

    return {"hops": enriched, "geo_available": geo_available, "notes": notes}


async def _enrich_one(hop, geo, reverse_resolver, asn_fallback) -> dict:
    ip = hop.get("ip")
    base = {
        "n": hop.get("n"),
        "ip": ip,
        "rdns": None,
        "asn": None,
        "org": None,
        "city": None,
        "rtt_ms": hop.get("rtt_ms"),
        "private": False,
        "unresponsive": hop.get("unresponsive", False),
        "hint": None,
    }

    # Nothing to enrich for a starred/absent hop.
    if not ip or base["unresponsive"]:
        return base

    # Private/reserved ranges: mark and skip all external lookups (scenario 4).
    if _is_private(ip):
        base["private"] = True
        return base

    # rDNS — independent per hop; a timeout on one never affects others.
    rdns = await _safe_reverse(reverse_resolver, ip)
    base["rdns"] = rdns

    # ASN / org (MaxMind, then optional Cymru fallback).
    _apply_asn(base, geo, ip, asn_fallback if asn_fallback else None)
    if asn_fallback is not None and base["asn"] in (None, "unknown"):
        fa, fo = await asn_fallback.lookup_asn(ip)
        if fa is not None or fo is not None:
            base["asn"], base["org"] = fa, fo

    # City (authoritative) + airport-code hint (separate signal).
    base["city"] = geo.lookup_city(ip) if geo.city_available else "unknown"
    base["hint"] = airport_hint(rdns)

    return base


def _apply_asn(base, geo, ip, _fallback) -> None:
    if geo.asn_available:
        asn, org = geo.lookup_asn(ip)
        base["asn"], base["org"] = asn, org
    else:
        # No DB: degrade to "unknown" (a Cymru fallback, if provided, overrides).
        base["asn"], base["org"] = "unknown", "unknown"


async def _safe_reverse(resolver: ReverseResolver | None, ip: str) -> str | None:
    if resolver is None:
        return None
    try:
        return await resolver.reverse(ip)
    except Exception:
        return None


def _is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
    )


# --- MaxMind downloader (spec §3.4, §9.1; exercised on boot in T21) -----------

_EDITIONS = ("GeoLite2-ASN", "GeoLite2-City")
_DOWNLOAD_URL = (
    "https://download.maxmind.com/app/geoip_download"
    "?edition_id={edition}&license_key={key}&suffix=tar.gz"
)


async def download_databases(license_key: str, dest_dir: str, *, client=None) -> list[str]:
    """Download + extract GeoLite2-ASN and GeoLite2-City .mmdb into ``dest_dir``.

    Returns the written paths. Raises EnrichmentConfigError without a key. The
    caller owns scheduling (T21 runs this on boot when the key is present).
    """
    if not license_key:
        raise EnrichmentConfigError("MAXMIND_LICENSE_KEY is not set")

    import httpx

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=60.0)
    written: list[str] = []
    try:
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        for edition in _EDITIONS:
            url = _DOWNLOAD_URL.format(edition=edition, key=license_key)
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            written.append(_extract_mmdb(response.content, edition, dest))
    finally:
        if own_client:
            await client.aclose()
    return written


def _extract_mmdb(tar_bytes: bytes, edition: str, dest: Path) -> str:
    """Pull the ``{edition}.mmdb`` member out of a GeoLite2 tar.gz."""
    with tarfile.open(fileobj=BytesIO(tar_bytes), mode="r:gz") as tar:
        member = next(
            (m for m in tar.getmembers() if m.name.endswith(f"{edition}.mmdb")), None
        )
        if member is None:
            raise EnrichmentConfigError(f"No {edition}.mmdb found in downloaded archive")
        source = tar.extractfile(member)
        if source is None:
            raise EnrichmentConfigError(f"Could not read {edition}.mmdb from archive")
        out_path = dest / f"{edition}.mmdb"
        out_path.write_bytes(source.read())
    return str(out_path)
