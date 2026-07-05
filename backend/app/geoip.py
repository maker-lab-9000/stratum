"""Boot-time GeoLite2 wiring (spec §3.4, §9.1; exercised on boot in T21).

Resolves the geo provider the pipeline enrichment uses: MaxMind GeoLite2 when the
offline `.mmdb` files are present (or downloadable via `MAXMIND_LICENSE_KEY`),
otherwise the null provider that degrades ASN/geo to "unknown". Downloading and
opening the databases must never stop the app from booting — every failure here
degrades to the null provider, it does not raise.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from app.collectors.enrichment import (
    MaxMindGeoProvider,
    NullGeoProvider,
    download_databases,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_DIR = "./data/geoip"


def _db_dir() -> Path:
    return Path(os.getenv("MAXMIND_DB_DIR", DEFAULT_DB_DIR))


def build_geo_provider():
    """Return the geo provider for the pipeline.

    If the GeoLite2 `.mmdb` files are missing but a licence key is set, download
    them once on boot. Any failure (no key, network/download error, unreadable
    DB) degrades to :class:`NullGeoProvider`; the rest of the pipeline still runs
    with ASN/geo shown as "unknown" (§3.4).
    """
    db_dir = _db_dir()
    asn = db_dir / "GeoLite2-ASN.mmdb"
    city = db_dir / "GeoLite2-City.mmdb"
    key = os.getenv("MAXMIND_LICENSE_KEY", "")

    if key and not (asn.exists() and city.exists()):
        try:
            written = asyncio.run(download_databases(key, str(db_dir)))
            logger.info("Downloaded GeoLite2 databases: %s", ", ".join(written))
        except Exception as exc:  # noqa: BLE001 — boot must survive any download error
            logger.warning(
                "GeoLite2 download failed (%s); ASN/geo will show 'unknown'. "
                "Check MAXMIND_LICENSE_KEY and outbound access.",
                exc,
            )

    if asn.exists() or city.exists():
        return MaxMindGeoProvider(
            asn_db_path=str(asn) if asn.exists() else None,
            city_db_path=str(city) if city.exists() else None,
        )

    logger.info(
        "No GeoLite2 databases in %s; ASN/geo will show 'unknown'. "
        "Set MAXMIND_LICENSE_KEY to enable offline enrichment.",
        db_dir,
    )
    return NullGeoProvider()
