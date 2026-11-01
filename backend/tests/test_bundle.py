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

import pytest

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


# --- 1.2.0: timing corroboration ----------------------------------------------

from app.pipeline.bundle import sample_timing_facts, seam, timing_section  # noqa: E402


def _timed(request, *, ttfb, connect=None, rtt=None, status=200, probe=False, peer="23.55.1.1", started=None):
    sample = _sample(request, 0, status=status)
    sample["peer_ip"] = peer
    sample["timing"] = {"connect_ms": connect, "tls_ms": None, "ttfb_ms": ttfb, "total_ms": ttfb,
                        "rtt_ms": rtt}
    if started is not None:
        sample["started_at_ms"] = started
    if probe:
        sample["probe"] = "cache_bust"
    return sample


def test_timing_section_arithmetic():
    samples = [
        _timed(1, ttfb=79.5, connect=95.0, rtt=38.2),
        _timed(2, ttfb=41.4),
        _timed(3, ttfb=42.0),
        _timed(4, ttfb=450.7, probe=True),
    ]
    timing = timing_section(samples)
    assert timing["edge_rtt_ms"] == 38.2
    assert timing["requests"] == [
        {"request": 1, "ttfb_ms": 79.5, "server_ms": 41.3},
        {"request": 2, "ttfb_ms": 41.4, "server_ms": 3.2},
        {"request": 3, "ttfb_ms": 42.0, "server_ms": 3.8},
    ]
    assert timing["server_ms_spread"] == {"min": 3.2, "median": 3.5, "max": 3.8, "count": 2}
    assert timing["cache_bust"] == {"ttfb_ms": 450.7, "server_ms": 412.5, "status": 200,
                                   "differing_headers": []}
    assert timing["facts"] == [
        "edge_rtt_ms: 38.2",
        "request 1 ttfb_ms: 79.5", "request 1 server_ms: 41.3",
        "request 2 ttfb_ms: 41.4", "request 2 server_ms: 3.2",
        "request 3 ttfb_ms: 42.0", "request 3 server_ms: 3.8",
        "warm server_ms min: 3.2", "warm server_ms median: 3.5", "warm server_ms max: 3.8",
        "cache_bust ttfb_ms: 450.7", "cache_bust server_ms: 412.5", "cache_bust status: 200",
        "cache_bust differing headers: none", "warm-varying headers: none",
    ]


def test_bundle_without_timing_fields():
    bundle = assemble_bundle(**akamai_inputs())
    assert bundle["timing"] == {"edge_rtt_ms": None, "requests": [], "cache_bust": None, "investigation": [], "facts": []}


def test_spread_omitted_with_one_warm_value():
    timing = timing_section([_timed(1, ttfb=79.5, rtt=38.2), _timed(2, ttfb=41.4)])
    assert "server_ms_spread" not in timing
    assert not any(f.startswith("warm ") for f in timing["facts"])


def test_wall_deltas():
    inputs = akamai_inputs()
    inputs["samples"] = [_timed(1, ttfb=1.0, started=0.0), _timed(2, ttfb=1.0, started=1500.0),
                         _timed(3, ttfb=1.0, started=3010.0)]
    assert assemble_bundle(**inputs)["progression"]["wall_deltas_s"] == [1.5, 1.5]
    inputs["samples"][1]["started_at_ms"] = None
    assert assemble_bundle(**inputs)["progression"]["wall_deltas_s"] == [None, None]


def test_probe_excluded_from_progression_and_success_check():
    inputs = akamai_inputs()
    inputs["samples"] = [_sample(1, 0), _sample(2, 5), _timed(3, ttfb=400.0, status=403, probe=True)]
    bundle = assemble_bundle(**inputs)
    assert bundle["progression"]["age_values"] == [0, 5]
    assert bundle["progression"]["status"] == [200, 200]
    inputs["samples"] = [_sample(1, 0, ok=False), _timed(2, ttfb=400.0, probe=True)]
    assert any(g["stage"] == "samples" for g in assemble_bundle(**inputs)["meta"]["gaps"])


_EDGE = {"n": 2, "ip": "23.55.1.1", "private": False, "unresponsive": False}
_DNS = {"a": ["23.55.1.1", "23.55.1.2"], "aaaa": []}


@pytest.mark.parametrize("hops,peers,dns,status", [
    ([_EDGE], ["23.55.1.1"], _DNS, "confirmed"),
    ([_EDGE], ["23.55.1.2"], _DNS, "different_edge"),
    ([{**_EDGE, "ip": "10.9.9.9"}], ["23.55.1.2"], _DNS, "unconfirmed"),
    ([], ["23.55.1.1"], _DNS, "unconfirmed"),
    ([_EDGE], [], _DNS, "unconfirmed"),
])
def test_seam_states(hops, peers, dns, status):
    samples = [_timed(i + 1, ttfb=1.0, peer=p) for i, p in enumerate(peers)]
    samples.append(_timed(9, ttfb=1.0, peer="198.51.100.7", probe=True))  # probe never counts
    result = seam(hops, samples, dns)
    assert result["status"] == status
    assert result["peer_ips"] == sorted(set(peers))
    assert result["traced_ip"] == (hops[0]["ip"] if hops else None)


def test_seam_stored_in_traceroute_and_different_edge_gap():
    inputs = akamai_inputs()
    inputs["dns"]["a"] = ["23.55.1.1", "23.55.1.2"]
    inputs["samples"] = [_timed(1, ttfb=1.0, peer="23.55.1.2")]
    bundle = assemble_bundle(**inputs)
    assert bundle["traceroute"]["seam"]["status"] == "different_edge"
    gap = next(g for g in bundle["meta"]["gaps"] if g["stage"] == "seam")
    assert "23.55.1.1" in gap["reason"] and "23.55.1.2" in gap["reason"]
    inputs["samples"] = [_timed(1, ttfb=1.0, peer="23.55.1.1")]
    assert not any(g["stage"] == "seam" for g in assemble_bundle(**inputs)["meta"]["gaps"])


def test_edge_rtt_ignores_connect_span_with_dns():
    """Final review fix: connect_ms includes DNS resolution; edge RTT comes only
    from the bare TCP rtt_ms (no fallback — a biased RTT invents false gaps)."""
    timing = timing_section([_timed(1, ttfb=50.0, connect=87.5, rtt=7.5), _timed(2, ttfb=9.0)])
    assert timing["edge_rtt_ms"] == 7.5
    assert timing["requests"][0]["server_ms"] == 42.5
    no_rtt = timing_section([_timed(1, ttfb=50.0, connect=87.5), _timed(2, ttfb=9.0)])
    assert no_rtt["edge_rtt_ms"] is None
    assert all(r["server_ms"] is None for r in no_rtt["requests"])



# --- 1.3.2: does the cache-bust response differ from the warm ones? -----------

def _headed(sample: dict, headers: list[list[str]]) -> dict:
    sample["headers"] = headers
    return sample


def test_identical_cache_bust_reports_no_differing_headers():
    # theguardian.com shape: only per-request values change, the probe included.
    base = [["Cache-Control", "max-age=60, private"], ["Age", "0"], ["ETag", 'W/"h1"']]
    def row(n, timer, rid, date):
        return base + [["x-timer", timer], ["x-request-id", rid], ["Date", date]]
    samples = [
        _headed(_timed(1, ttfb=35.5, rtt=21.4), row(1, "S1,VS0,VE9", "a", "d1")),
        _headed(_timed(2, ttfb=26.1), row(2, "S2,VS0,VE1", "b", "d1")),
        _headed(_timed(3, ttfb=29.7), row(3, "S3,VS0,VE2", "c", "d1")),
        _headed(_timed(4, ttfb=44.6, probe=True), row(4, "S4,VS0,VE2", "d", "d2")),
    ]
    timing = timing_section(samples)
    assert "cache_bust differing headers: none" in timing["facts"]
    assert "warm-varying headers: x-request-id, x-timer" in timing["facts"]
    assert timing["cache_bust"]["differing_headers"] == []
    assert timing["warm_varying_headers"] == ["x-request-id", "x-timer"]


def test_cache_bust_differences_compare_against_warm_requests_only():
    # Request 1 is the cold miss: the probe is compared with requests 2..N.
    def warm(n, cache):
        return _headed(_timed(n, ttfb=30.0, rtt=20.0 if n == 1 else None),
                       [["X-Cache", cache], ["Cache-Control", "max-age=300"]])
    probe = _headed(_timed(4, ttfb=290.0, probe=True),
                    [["x-cache", "BYPASS"], ["cache-control", "no-store"], ["set-cookie", "a=1"]])
    timing = timing_section([warm(1, "MISS"), warm(2, "HIT"), warm(3, "HIT"), probe])
    assert "cache_bust differing headers: cache-control, set-cookie, x-cache" in timing["facts"]
    assert "warm-varying headers: none" in timing["facts"]


def test_no_header_diff_without_a_usable_probe():
    requests = [_timed(1, ttfb=30.0, rtt=20.0), _timed(2, ttfb=31.0)]
    assert not any("differing headers" in f for f in timing_section(requests)["facts"])
    failed = _timed(3, ttfb=None, probe=True)
    failed.update({"ok": False, "headers": []})
    facts = timing_section(requests + [failed])["facts"]
    assert not any("differing headers" in f or "warm-varying" in f for f in facts)


def test_timing_section_keeps_investigation_out_of_requests_and_probe():
    # 1.4.0: an investigation request (even a cache-busting one) is not one of
    # the N requests and not the cache-bust probe; it gets its own rows + facts.
    inv = _timed(3, ttfb=200.0)
    inv["probe"] = "investigation"
    inv["investigation"] = {"n": 1, "headers": {}, "cache_bust": True, "reason": "r"}
    section = timing_section([_timed(1, ttfb=30.0, rtt=20.0), _timed(2, ttfb=28.0), inv])
    assert [r["request"] for r in section["requests"]] == [1, 2]
    assert section["cache_bust"] is None
    assert section["investigation"] == [{"request": 3, "ttfb_ms": 200.0, "server_ms": 180.0}]
    assert "request 3 ttfb_ms: 200.0" in section["facts"]
    assert "request 3 server_ms: 180.0" in section["facts"]


def test_sample_timing_facts_shape():
    assert sample_timing_facts(_timed(7, ttfb=41.2), 20) == {
        "request": 7, "ttfb_ms": 41.2, "server_ms": 21.2,
        "facts": ["request 7 ttfb_ms: 41.2", "request 7 server_ms: 21.2"]}
    assert sample_timing_facts(_timed(7, ttfb=41.2), None) == {
        "request": 7, "ttfb_ms": 41.2, "server_ms": None, "facts": ["request 7 ttfb_ms: 41.2"]}



def test_assemble_bundle_keeps_investigation_samples_out_of_progression_and_seam():
    inputs = akamai_inputs()
    inv = _sample(9, 5)
    inv.update({"probe": "investigation", "peer_ip": "9.9.9.9",
                "investigation": {"n": 1, "headers": {}, "cache_bust": False, "reason": "r"}})
    inputs["samples"] = list(inputs["samples"]) + [inv]
    bundle = assemble_bundle(**inputs)
    assert 9 not in [None] and len(bundle["progression"]["age_values"]) == len(inputs["samples"]) - 1
    assert "9.9.9.9" not in bundle["traceroute"]["seam"]["peer_ips"]
