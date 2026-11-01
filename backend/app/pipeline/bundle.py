"""Evidence bundle assembler (spec §2, §3 stage 5, §4.3).

A **pure** function that stitches the collector outputs into the single evidence
bundle the LLM receives (T12). It does **zero interpretation**: it copies DNS,
samples, warm timing, and enriched hops verbatim, and computes only *arithmetic*
over the numbers (Age deltas). There are deliberately no ``vendor``/``hit``/
``miss``/``layer``/``verdict`` fields anywhere — that knowledge lives only in the
LLM prompt (§2). A regression test guards against interpretation creep.

The bundle is also the storage contract: ``dns``, ``samples``, and ``traceroute``
are stored verbatim into ``dns_json`` / ``samples_json`` / ``traceroute_json``.
"""

from __future__ import annotations

import statistics
from typing import Any

from app.collectors.http_sampler import is_probe


def assemble_bundle(
    *,
    url: str,
    dns: dict | None,
    samples: list[dict] | None,
    warm: dict | None,
    traceroute: dict | None,
    enrichment: dict | None,
    vantage: str | None = None,
    request_options: dict | None = None,
) -> dict:
    """Assemble the evidence bundle from raw collector outputs.

    Inputs are the verbatim returns of T03 (dns), T04 (samples), T05 (warm),
    T06 (traceroute), T07 (enrichment). Returns a JSON-serializable dict.
    """
    samples = samples or []
    requests = [s for s in samples if not is_probe(s)]
    merged_traceroute = _merge_traceroute(traceroute, enrichment)
    merged_traceroute["seam"] = seam(merged_traceroute["hops"], samples, dns)

    return {
        "meta": {
            "url": url,
            "vantage": vantage,
            "request_options": request_options or {},
            # Stages that failed/degraded, so the LLM (and UI) see the gaps
            # explicitly rather than inferring from absence.
            "gaps": _gaps(dns, requests, merged_traceroute),
        },
        "dns": dns,
        "samples": samples,
        "warm": warm,
        "progression": _progression(requests),
        "timing": timing_section(samples),
        "traceroute": merged_traceroute,
    }


# --- progression (arithmetic only, §4.3) --------------------------------------

def _progression(samples: list[dict]) -> dict:
    """Per-sample numbers the LLM interprets: Age values + deltas, Cache-Control,
    status, timing. Purely arithmetic — no hit/miss judgement here."""
    ages = [_parse_int(_header_value(s, "Age")) for s in samples]
    deltas: list[int | None] = []
    for prev, curr in zip(ages, ages[1:]):
        deltas.append(curr - prev if prev is not None and curr is not None else None)

    starts = [s.get("started_at_ms") for s in samples]
    wall: list[float | None] = []
    for prev, curr in zip(starts, starts[1:]):
        wall.append(round((curr - prev) / 1000, 1) if prev is not None and curr is not None else None)

    return {
        "age_values": ages,
        "age_deltas": deltas,
        "wall_deltas_s": wall,
        "cache_control": [_header_value(s, "Cache-Control") for s in samples],
        "status": [s.get("status") for s in samples],
        "elapsed_ms": [s.get("elapsed_ms") for s in samples],
    }


# --- timing (arithmetic only, 1.2.0) ------------------------------------------

def _r(value: float) -> float:
    return round(value, 1)


def _ttfb(sample: dict) -> float | None:
    timing = sample.get("timing") or {}
    value = timing.get("ttfb_ms")
    return value if isinstance(value, (int, float)) else None


def _header_values(sample: dict) -> dict[str, str]:
    """Lower-cased header name → verbatim value (repeats joined with ", ")."""
    out: dict[str, list[str]] = {}
    for pair in sample.get("headers") or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            out.setdefault(str(pair[0]).lower(), []).append(str(pair[1]))
    return {k: ", ".join(v) for k, v in out.items()}


def cache_bust_header_diff(requests: list[dict], probe: dict) -> tuple[list[str], list[str]]:
    """(1.3.2) Which headers the cache-bust response changed, by value only.

    Compared against the warm requests (2..N; request 1 is often the cold
    miss). Headers whose value already varies between warm requests are
    per-request noise — returned separately, never counted as a difference.
    ``Date`` is skipped (the clock). Returns (differing, warm_varying), sorted."""
    warm = requests[1:] if len(requests) >= 2 else requests
    warm_values = [_header_values(s) for s in warm]
    probe_values = _header_values(probe)
    names = {n for v in warm_values for n in v} | set(probe_values)
    names.discard("date")
    varying, differing = [], []
    for name in sorted(names):
        seen = {v.get(name) for v in warm_values}
        if len(seen) > 1:
            varying.append(name)
        elif probe_values.get(name) not in seen:
            differing.append(name)
    return differing, varying


def timing_section(samples: list[dict]) -> dict:
    """Edge round trip, per-request server time and its spread, the cache-bust
    probe baseline, and the exact fact strings the LLM may cite. Numbers only —
    what they mean is the prompt's business (§2)."""
    requests = [s for s in samples if not is_probe(s)]
    probe = next((s for s in samples if is_probe(s)), None)

    # Edge RTT = the sampler's bare TCP connect to the peer IP (rtt_ms). Never
    # connect_ms: httpcore's connect span includes DNS resolution, which would
    # bias every server_ms low and invite false "edge-speed" gaps.
    edge_rtt = None
    for sample in requests:
        rtt = (sample.get("timing") or {}).get("rtt_ms")
        if isinstance(rtt, (int, float)):
            edge_rtt = rtt
            break

    def server(ttfb: float | None) -> float | None:
        return _r(ttfb - edge_rtt) if ttfb is not None and edge_rtt is not None else None

    facts: list[str] = []
    if edge_rtt is not None:
        facts.append(f"edge_rtt_ms: {_r(edge_rtt)}")

    rows = []
    for sample in requests:
        ttfb = _ttfb(sample)
        if ttfb is None:
            continue
        row = {"request": sample.get("request"), "ttfb_ms": _r(ttfb), "server_ms": server(ttfb)}
        rows.append(row)
        facts.append(f"request {row['request']} ttfb_ms: {row['ttfb_ms']}")
        if row["server_ms"] is not None:
            facts.append(f"request {row['request']} server_ms: {row['server_ms']}")

    section: dict = {"edge_rtt_ms": _r(edge_rtt) if edge_rtt is not None else None, "requests": rows}

    warm = [r["server_ms"] for r in rows[1:] if r["server_ms"] is not None]
    if len(warm) >= 2:
        spread = {"min": min(warm), "median": _r(statistics.median(warm)), "max": max(warm),
                  "count": len(warm)}
        section["server_ms_spread"] = spread
        facts += [f"warm server_ms {k}: {spread[k]}" for k in ("min", "median", "max")]

    cache_bust = None
    if probe is not None:
        ttfb = _ttfb(probe)
        cache_bust = {"ttfb_ms": _r(ttfb) if ttfb is not None else None,
                      "server_ms": server(ttfb), "status": probe.get("status")}
        if cache_bust["ttfb_ms"] is not None:
            facts.append(f"cache_bust ttfb_ms: {cache_bust['ttfb_ms']}")
        if cache_bust["server_ms"] is not None:
            facts.append(f"cache_bust server_ms: {cache_bust['server_ms']}")
        if cache_bust["status"] is not None:
            facts.append(f"cache_bust status: {cache_bust['status']}")
        # 1.3.2: a probe that looks like the warm responses proves no miss.
        if requests and probe.get("ok", True) and probe.get("headers"):
            differing, varying = cache_bust_header_diff(requests, probe)
            cache_bust["differing_headers"] = differing
            section["warm_varying_headers"] = varying
            facts.append(f"cache_bust differing headers: {', '.join(differing) or 'none'}")
            facts.append(f"warm-varying headers: {', '.join(varying) or 'none'}")
    section["cache_bust"] = cache_bust
    section["facts"] = facts
    return section


# --- seam: does the route end where the samples connected? --------------------

def seam(hops: list[dict], samples: list[dict], dns: dict | None) -> dict:
    """``confirmed`` — traced edge IP is one the samples connected to;
    ``different_edge`` — traced IP is another DNS address for the hostname;
    ``unconfirmed`` — anything else (trace stopped short, no peer IP)."""
    traced = None
    for hop in reversed(hops or []):
        if isinstance(hop, dict) and hop.get("ip") and not hop.get("unresponsive") and not hop.get("private"):
            traced = hop["ip"]
            break
    peers = sorted({s["peer_ip"] for s in samples if not is_probe(s) and s.get("peer_ip")})
    records = set()
    if isinstance(dns, dict):
        records = set(dns.get("a") or []) | set(dns.get("aaaa") or [])
    if traced and traced in peers:
        status = "confirmed"
    elif traced and peers and traced in records:
        status = "different_edge"
    else:
        status = "unconfirmed"
    return {"status": status, "traced_ip": traced, "peer_ips": peers}


# --- traceroute + enrichment merge --------------------------------------------

def _merge_traceroute(traceroute: dict | None, enrichment: dict | None) -> dict:
    """Combine traceroute metadata with the enriched hop list (T07 replaces the
    raw hops)."""
    traceroute = traceroute or {}
    enrichment = enrichment or {}
    return {
        "tool": traceroute.get("tool"),
        "target": traceroute.get("target"),
        "port": traceroute.get("port"),
        "timed_out": traceroute.get("timed_out", False),
        "error": traceroute.get("error"),
        "hops": enrichment.get("hops", traceroute.get("hops", [])),
        "geo_available": enrichment.get("geo_available", False),
        "enrichment_notes": enrichment.get("notes", []),
    }


# --- gap detection ------------------------------------------------------------

def _gaps(dns: dict | None, samples: list[dict], traceroute: dict) -> list[dict]:
    gaps: list[dict] = []
    if not dns or (isinstance(dns, dict) and dns.get("error")):
        reason = dns.get("error") if isinstance(dns, dict) else "DNS not collected"
        gaps.append({"stage": "dns", "reason": _reason_text(reason)})
    if not samples or all(not s.get("ok") for s in samples):
        gaps.append({"stage": "samples", "reason": "no successful samples"})
    if traceroute.get("error"):
        gaps.append({"stage": "traceroute", "reason": _reason_text(traceroute["error"])})
    seam_info = traceroute.get("seam") or {}
    if seam_info.get("status") == "different_edge":
        gaps.append({
            "stage": "seam",
            "reason": f"route reached {seam_info['traced_ip']}; samples connected to "
                      f"{', '.join(seam_info['peer_ips'])}",
        })
    return gaps


# --- helpers ------------------------------------------------------------------

def _header_value(sample: dict, name: str) -> str | None:
    """First header value matching ``name`` (case-insensitive) in a sample's
    verbatim [name, value] pairs, or None."""
    for pair in sample.get("headers", []):
        if len(pair) == 2 and pair[0].lower() == name.lower():
            return pair[1]
    return None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _reason_text(err: Any) -> str:
    if isinstance(err, dict):
        return err.get("message") or err.get("type") or "error"
    return str(err)
