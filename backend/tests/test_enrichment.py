"""T07 — network enrichment (spec §3.4, §4.4).

Scenarios:
  1. Fixture MaxMind DBs: known IP -> correct ASN, org, city.
  2. No MaxMind DB -> fields "unknown", no crash, degradation note.
  3. rDNS `f-ed4.ffm.de.net` -> hint FRA/Frankfurt, distinct from MaxMind city.
  4. Private IPs -> marked private, no external lookup attempted.
  5. rDNS timeout -> hop keeps IP, rdns null, other hops unaffected.

Real GeoLite2 .mmdb fixtures are built at test time with mmdb_writer; rDNS and
the Cymru fallback are faked (no live network).
"""

import json
import tarfile
from io import BytesIO

import httpx
import pytest
import respx
from mmdb_writer import MMDBWriter
from netaddr import IPSet

from app.collectors.enrichment import (
    CymruAsnFallback,
    MaxMindGeoProvider,
    NullGeoProvider,
    airport_hint,
    download_databases,
    enrich_hops,
)

ENRICHED_KEYS = {
    "n", "ip", "rdns", "asn", "org", "city", "rtt_ms", "private", "unresponsive", "hint"
}


# --- fixtures -----------------------------------------------------------------

@pytest.fixture(scope="session")
def maxmind_dbs(tmp_path_factory):
    d = tmp_path_factory.mktemp("mmdb")
    asn_path = d / "GeoLite2-ASN.mmdb"
    city_path = d / "GeoLite2-City.mmdb"

    w = MMDBWriter(ip_version=4, database_type="GeoLite2-ASN", languages=["en"])
    w.insert_network(
        IPSet(["23.55.0.0/16"]),
        {"autonomous_system_number": 20940, "autonomous_system_organization": "Akamai Technologies"},
    )
    w.to_db_file(str(asn_path))

    wc = MMDBWriter(ip_version=4, database_type="GeoLite2-City", languages=["en"])
    wc.insert_network(
        IPSet(["23.55.0.0/16"]),
        {"city": {"names": {"en": "Frankfurt am Main"}}, "country": {"names": {"en": "Germany"}}},
    )
    wc.to_db_file(str(city_path))
    return str(asn_path), str(city_path)


@pytest.fixture
def geo(maxmind_dbs):
    return MaxMindGeoProvider(*maxmind_dbs)


class FakeReverse:
    def __init__(self, mapping=None, timeout_ips=()):
        self.mapping = mapping or {}
        self.timeout_ips = set(timeout_ips)
        self.calls: list[str] = []

    async def reverse(self, ip):
        self.calls.append(ip)
        if ip in self.timeout_ips:
            raise TimeoutError("simulated rDNS timeout")
        return self.mapping.get(ip)


def _hop(n, ip, **kw):
    return {"n": n, "ip": ip, "rtt_ms": kw.get("rtt_ms", 10.0), "unresponsive": kw.get("unresponsive", False)}


# --- Scenario 1 ---------------------------------------------------------------

async def test_maxmind_lookup_asn_org_city(geo):
    result = await enrich_hops([_hop(1, "23.55.1.1")], geo=geo)
    hop = result["hops"][0]
    assert hop["asn"] == 20940
    assert hop["org"] == "Akamai Technologies"
    assert hop["city"] == "Frankfurt am Main"
    assert result["geo_available"] is True
    assert result["notes"] == []
    assert set(hop) == ENRICHED_KEYS
    assert json.loads(json.dumps(result)) == result


async def test_ip_not_in_db_is_null_not_unknown(geo):
    result = await enrich_hops([_hop(1, "8.8.8.8")], geo=geo)
    hop = result["hops"][0]
    # DB present but no record -> genuine null (distinct from "unknown"=no DB).
    assert hop["asn"] is None and hop["org"] is None
    assert hop["city"] is None


# --- Scenario 2 ---------------------------------------------------------------

async def test_no_maxmind_db_degrades_to_unknown():
    result = await enrich_hops([_hop(1, "23.55.1.1")], geo=NullGeoProvider())
    hop = result["hops"][0]
    assert hop["asn"] == "unknown"
    assert hop["org"] == "unknown"
    assert hop["city"] == "unknown"
    assert result["geo_available"] is False
    assert result["notes"] and "MaxMind" in result["notes"][0]


async def test_missing_db_paths_also_degrade():
    geo = MaxMindGeoProvider("/no/such/asn.mmdb", "/no/such/city.mmdb")
    assert geo.asn_available is False and geo.city_available is False
    result = await enrich_hops([_hop(1, "23.55.1.1")], geo=geo)
    assert result["hops"][0]["org"] == "unknown"


# --- Scenario 3 ---------------------------------------------------------------

async def test_airport_hint_distinct_from_city(geo):
    reverse = FakeReverse({"23.55.1.1": "f-ed4.ffm.de.net"})
    result = await enrich_hops([_hop(1, "23.55.1.1")], geo=geo, reverse_resolver=reverse)
    hop = result["hops"][0]
    assert hop["hint"] == "FRA/Frankfurt"
    assert hop["city"] == "Frankfurt am Main"
    assert hop["hint"] != hop["city"]  # hint is a separate signal from MaxMind city
    assert hop["rdns"] == "f-ed4.ffm.de.net"


def test_airport_hint_parsing_variants():
    assert airport_hint("f-ed4.ffm.de.net") == "FRA/Frankfurt"
    assert airport_hint("ae-1.r01.ams1.nl.example.net") == "AMS/Amsterdam"  # digits stripped
    assert airport_hint("xe-0-0.border-fra1.example.net") == "FRA/Frankfurt"  # digits stripped
    # Conservative on purpose: only whole tokens match, so no false positive
    # from "ams" buried inside another word.
    assert airport_hint("streams.example.net") is None
    assert airport_hint("no-location-here.example.net") is None
    assert airport_hint(None) is None


# --- Scenario 4 ---------------------------------------------------------------

async def test_private_ips_skip_lookups(geo):
    reverse = FakeReverse({"10.0.0.5": "should-not-be-used"})
    hops = [_hop(1, "10.0.0.5"), _hop(2, "192.168.1.1")]
    result = await enrich_hops(hops, geo=geo, reverse_resolver=reverse)

    for hop in result["hops"]:
        assert hop["private"] is True
        assert hop["rdns"] is None
        assert hop["asn"] is None and hop["org"] is None
        assert hop["city"] is None
        assert hop["hint"] is None
    # No reverse lookup was attempted for private hops.
    assert reverse.calls == []


# --- Scenario 5 ---------------------------------------------------------------

async def test_rdns_timeout_isolated(geo):
    reverse = FakeReverse(
        mapping={"23.55.1.2": "edge.akamai.example.net"},
        timeout_ips={"23.55.1.1"},
    )
    hops = [_hop(1, "23.55.1.1"), _hop(2, "23.55.1.2")]
    result = await enrich_hops(hops, geo=geo, reverse_resolver=reverse)

    first, second = result["hops"]
    # Timed-out hop keeps its IP but rdns is null...
    assert first["ip"] == "23.55.1.1"
    assert first["rdns"] is None
    assert first["asn"] == 20940  # geo enrichment still happened
    # ...and the other hop is unaffected.
    assert second["rdns"] == "edge.akamai.example.net"


# --- unresponsive passthrough -------------------------------------------------

async def test_unresponsive_hop_passthrough(geo):
    hops = [{"n": 3, "ip": None, "rtt_ms": None, "unresponsive": True}]
    result = await enrich_hops(hops, geo=geo)
    hop = result["hops"][0]
    assert hop["unresponsive"] is True
    assert hop["ip"] is None and hop["asn"] is None
    assert set(hop) == ENRICHED_KEYS


# --- Cymru fallback (opt-in) --------------------------------------------------

async def test_cymru_fallback_fills_asn_when_no_maxmind():
    async def fake_txt(name):
        if name.endswith("origin.asn.cymru.com"):
            return ["20940 | 23.55.0.0/16 | US | arin | 2010-01-01"]
        if name.startswith("AS20940"):
            return ["20940 | US | arin | 2010-01-01 | AKAMAI-AS, US"]
        return []

    fallback = CymruAsnFallback(fake_txt)
    result = await enrich_hops(
        [_hop(1, "23.55.1.1")], geo=NullGeoProvider(), asn_fallback=fallback
    )
    hop = result["hops"][0]
    assert hop["asn"] == 20940
    assert hop["org"] == "AKAMAI-AS, US"


async def test_cymru_fallback_ipv4_only():
    async def fake_txt(name):
        raise AssertionError("should not query for IPv6")

    fallback = CymruAsnFallback(fake_txt)
    assert await fallback.lookup_asn("2606:2800::1") == (None, None)


# --- MaxMind downloader -------------------------------------------------------

def _make_tar(edition: str, payload: bytes) -> bytes:
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=f"{edition}_20240101/{edition}.mmdb")
        info.size = len(payload)
        tar.addfile(info, BytesIO(payload))
    return buf.getvalue()


@respx.mock
async def test_download_databases_extracts_mmdb(tmp_path):
    tars = {
        "GeoLite2-ASN": _make_tar("GeoLite2-ASN", b"ASN-DB-BYTES"),
        "GeoLite2-City": _make_tar("GeoLite2-City", b"CITY-DB-BYTES"),
    }

    def responder(request):
        edition = "GeoLite2-ASN" if "GeoLite2-ASN" in str(request.url) else "GeoLite2-City"
        return httpx.Response(200, content=tars[edition])

    respx.get(url__regex=r"download\.maxmind\.com").mock(side_effect=responder)

    paths = await download_databases("fake-key", str(tmp_path))
    assert len(paths) == 2
    assert (tmp_path / "GeoLite2-ASN.mmdb").read_bytes() == b"ASN-DB-BYTES"
    assert (tmp_path / "GeoLite2-City.mmdb").read_bytes() == b"CITY-DB-BYTES"


async def test_download_without_key_raises():
    from app.collectors.enrichment import EnrichmentConfigError

    with pytest.raises(EnrichmentConfigError):
        await download_databases("", "/tmp/whatever")


# --- live smoke (excluded by default) ----------------------------------------

@pytest.mark.live
async def test_live_reverse_dns_enrichment():
    from app.collectors.enrichment import DnspythonReverseResolver

    result = await enrich_hops(
        [_hop(1, "8.8.8.8")],
        geo=NullGeoProvider(),
        reverse_resolver=DnspythonReverseResolver(),
    )
    assert result["hops"][0]["rdns"]  # e.g. dns.google
