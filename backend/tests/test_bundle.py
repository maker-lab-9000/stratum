"""T08 — evidence bundle assembler (spec §2, §3 stage 5, §4.3).

Scenarios:
  1. Golden test: full fixture inputs -> bundle matches golden JSON snapshot.
  2. Age progression arithmetic: [0,0,0,0]->[0,0,0]; [12,14,49]->[2,35];
     missing Age -> null slot, no crash.
  3. Schema guard: NO keys named vendor|hit|miss|layer|verdict anywhere.
  4. Partial evidence (traceroute failed) -> bundle valid + typed gap flag.
"""

import json
from pathlib import Path

from app.pipeline.bundle import assemble_bundle

GOLDEN = Path(__file__).parent / "fixtures" / "bundle" / "golden_bundle.json"


def _sample(request, age, *, cache_control="no-cache, no-store", status=200, ok=True):
    """A verbatim sample with an Age header (or None to omit it)."""
    headers = [
        ["Server", "AkamaiGHost"],
        ["Via", "1.1 v1-akamaitech.net"],
        ["X-Cache", "TCP_MISS from a23-fra"],
    ]
    if age is not None:
        headers.append(["Age", str(age)])
    if cache_control is not None:
        headers.append(["Cache-Control", cache_control])
    return {
        "request": request,
        "ok": ok,
        "status": status,
        "http_version": "HTTP/2",
        "url": "https://www.example-foods.com/",
        "headers": headers if ok else [],
        "elapsed_ms": 40.0 + request,
        "started_at_ms": (request - 1) * 250.0,
        "error": None,
    }


def akamai_inputs():
    """Representative collector outputs — the mockup's 'CDN bypass' story."""
    dns = {
        "a": ["23.55.1.1"],
        "aaaa": [],
        "cname_chain": [
            {"name": "www.example-foods.com", "cname": "example-foods.com.edgekey.net", "ttl": 300},
            {"name": "example-foods.com.edgekey.net", "cname": "e123.akamaiedge.net", "ttl": 20},
        ],
        "ns": ["ns1.example-foods.com", "ns2.example-foods.com"],
        "ttl": 20,
        "truncated": False,
    }
    samples = [_sample(i, 0) for i in range(1, 5)]  # flat Age 0 = bypass
    warm = {
        "warmed": True,
        "skipped": False,
        "error": None,
        "timing": {"status": 200, "final_url": "https://www.example-foods.com/", "ttfb_ms": 45, "load_ms": 210, "dom_content_loaded_ms": 150, "duration_ms": 210},
    }
    traceroute = {
        "tool": "mtr",
        "target": "e123.akamaiedge.net",
        "port": 443,
        "timed_out": False,
        "error": None,
        "hops": [{"n": 1, "ip": "192.168.1.1", "rtt_ms": 0.7, "unresponsive": False}],
    }
    enrichment = {
        "hops": [
            {"n": 1, "ip": "192.168.1.1", "rdns": None, "asn": None, "org": None, "city": None, "rtt_ms": 0.7, "private": True, "unresponsive": False, "hint": None},
            {"n": 2, "ip": "23.55.1.1", "rdns": "a23-55-1-1.deploy.static.akamaitechnologies.com", "asn": 20940, "org": "Akamai Technologies", "city": "Frankfurt am Main", "rtt_ms": 15.0, "private": False, "unresponsive": False, "hint": "FRA/Frankfurt"},
        ],
        "geo_available": True,
        "notes": [],
    }
    return {
        "url": "https://www.example-foods.com/",
        "dns": dns,
        "samples": samples,
        "warm": warm,
        "traceroute": traceroute,
        "enrichment": enrichment,
        "vantage": "Berlin, DE · homelab",
        "request_options": {"request_count": 4, "interval_ms": 250, "warm": True},
    }


# --- Scenario 1 ---------------------------------------------------------------

def test_golden_bundle_snapshot():
    bundle = assemble_bundle(**akamai_inputs())
    golden = json.loads(GOLDEN.read_text())
    assert bundle == golden


def test_bundle_is_json_serializable():
    bundle = assemble_bundle(**akamai_inputs())
    assert json.loads(json.dumps(bundle)) == bundle


def test_traceroute_uses_enriched_hops():
    bundle = assemble_bundle(**akamai_inputs())
    hops = bundle["traceroute"]["hops"]
    # Enriched hops (with asn/org/city), not the raw 1-hop traceroute list.
    assert len(hops) == 2
    assert hops[1]["org"] == "Akamai Technologies"


# --- Scenario 2 ---------------------------------------------------------------

def test_age_deltas_flat_zero():
    inputs = akamai_inputs()
    inputs["samples"] = [_sample(i, 0) for i in range(1, 5)]
    prog = assemble_bundle(**inputs)["progression"]
    assert prog["age_values"] == [0, 0, 0, 0]
    assert prog["age_deltas"] == [0, 0, 0]


def test_age_deltas_climbing():
    inputs = akamai_inputs()
    inputs["samples"] = [_sample(1, 12), _sample(2, 14), _sample(3, 49)]
    prog = assemble_bundle(**inputs)["progression"]
    assert prog["age_values"] == [12, 14, 49]
    assert prog["age_deltas"] == [2, 35]


def test_missing_age_null_slot_no_crash():
    inputs = akamai_inputs()
    inputs["samples"] = [_sample(1, 12), _sample(2, None), _sample(3, 49)]
    prog = assemble_bundle(**inputs)["progression"]
    assert prog["age_values"] == [12, None, 49]
    # Deltas touching a null slot are null, not a crash.
    assert prog["age_deltas"] == [None, None]


def test_failed_sample_has_null_progression_slots():
    inputs = akamai_inputs()
    inputs["samples"] = [_sample(1, 5), _sample(2, None, ok=False)]
    prog = assemble_bundle(**inputs)["progression"]
    assert prog["age_values"] == [5, None]
    assert prog["cache_control"][1] is None


# --- Scenario 3 ---------------------------------------------------------------

def _all_keys(obj):
    keys = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.add(key)
            keys |= _all_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _all_keys(item)
    return keys


def test_no_interpretation_keys_anywhere():
    bundle = assemble_bundle(**akamai_inputs())
    forbidden = ("vendor", "hit", "miss", "layer", "verdict")
    offenders = {
        key for key in _all_keys(bundle) if any(f in key.lower() for f in forbidden)
    }
    assert offenders == set(), f"interpretation keys leaked into the bundle: {offenders}"


# --- Scenario 4 ---------------------------------------------------------------

def test_traceroute_failure_recorded_as_gap():
    inputs = akamai_inputs()
    inputs["traceroute"] = {
        "tool": "mtr",
        "target": "e123.akamaiedge.net",
        "port": 443,
        "timed_out": False,
        "error": {"type": "TraceroutePermissionError", "message": "raw socket denied", "hint": "grant NET_RAW"},
        "hops": [],
    }
    inputs["enrichment"] = {"hops": [], "geo_available": False, "notes": []}
    bundle = assemble_bundle(**inputs)

    # Bundle still valid, rest of evidence intact.
    assert bundle["dns"]["a"] == ["23.55.1.1"]
    assert bundle["samples"]
    # Gap flag present and typed.
    gaps = bundle["meta"]["gaps"]
    assert {"stage": "traceroute", "reason": "raw socket denied"} in gaps


def test_dns_failure_recorded_as_gap():
    inputs = akamai_inputs()
    inputs["dns"] = {"error": {"type": "DnsNXDomain", "message": "NXDOMAIN: nope.invalid"}}
    bundle = assemble_bundle(**inputs)
    assert {"stage": "dns", "reason": "NXDOMAIN: nope.invalid"} in bundle["meta"]["gaps"]


def test_no_gaps_on_healthy_inputs():
    bundle = assemble_bundle(**akamai_inputs())
    assert bundle["meta"]["gaps"] == []
