"""Boot-time geo wiring (T21). build_geo_provider must never raise — every
failure degrades to the null provider so the app still boots (§3.4)."""

from __future__ import annotations

import pytest
from mmdb_writer import MMDBWriter
from netaddr import IPSet

from app import geoip
from app.collectors.enrichment import MaxMindGeoProvider, NullGeoProvider


def _write_dbs(dest):
    """Build minimal real GeoLite2-ASN/City .mmdb files with the expected names."""
    w = MMDBWriter(ip_version=4, database_type="GeoLite2-ASN", languages=["en"])
    w.insert_network(IPSet(["23.55.0.0/16"]), {"autonomous_system_number": 20940})
    w.to_db_file(str(dest / "GeoLite2-ASN.mmdb"))
    wc = MMDBWriter(ip_version=4, database_type="GeoLite2-City", languages=["en"])
    wc.insert_network(IPSet(["23.55.0.0/16"]), {"city": {"names": {"en": "Frankfurt"}}})
    wc.to_db_file(str(dest / "GeoLite2-City.mmdb"))


def test_no_key_no_files_degrades_to_null(monkeypatch, tmp_path):
    monkeypatch.setenv("MAXMIND_DB_DIR", str(tmp_path))
    monkeypatch.delenv("MAXMIND_LICENSE_KEY", raising=False)
    assert isinstance(geoip.build_geo_provider(), NullGeoProvider)


def test_download_failure_degrades_to_null(monkeypatch, tmp_path):
    # Key present but the download blows up -> still boots on the null provider.
    monkeypatch.setenv("MAXMIND_DB_DIR", str(tmp_path))
    monkeypatch.setenv("MAXMIND_LICENSE_KEY", "some-key")

    def _boom(*_a, **_k):
        raise RuntimeError("network down")

    monkeypatch.setattr(geoip, "download_databases", _boom)
    provider = geoip.build_geo_provider()  # must not raise
    assert isinstance(provider, NullGeoProvider)


def test_existing_databases_are_used(monkeypatch, tmp_path):
    _write_dbs(tmp_path)
    monkeypatch.setenv("MAXMIND_DB_DIR", str(tmp_path))
    monkeypatch.delenv("MAXMIND_LICENSE_KEY", raising=False)  # no download needed
    provider = geoip.build_geo_provider()
    assert isinstance(provider, MaxMindGeoProvider)
    assert provider.asn_available and provider.city_available


def test_present_databases_skip_download(monkeypatch, tmp_path):
    # With both DBs already on disk, a set key must not trigger a download.
    _write_dbs(tmp_path)
    monkeypatch.setenv("MAXMIND_DB_DIR", str(tmp_path))
    monkeypatch.setenv("MAXMIND_LICENSE_KEY", "some-key")

    def _fail(*_a, **_k):  # would raise if called
        raise AssertionError("download should be skipped when DBs exist")

    monkeypatch.setattr(geoip, "download_databases", _fail)
    assert isinstance(geoip.build_geo_provider(), MaxMindGeoProvider)
