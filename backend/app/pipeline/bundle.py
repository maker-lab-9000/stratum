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

from typing import Any


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
    merged_traceroute = _merge_traceroute(traceroute, enrichment)

    return {
        "meta": {
            "url": url,
            "vantage": vantage,
            "request_options": request_options or {},
            # Stages that failed/degraded, so the LLM (and UI) see the gaps
            # explicitly rather than inferring from absence.
            "gaps": _gaps(dns, samples, merged_traceroute),
        },
        "dns": dns,
        "samples": samples,
        "warm": warm,
        "progression": _progression(samples),
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

    return {
        "age_values": ages,
        "age_deltas": deltas,
        "cache_control": [_header_value(s, "Cache-Control") for s in samples],
        "status": [s.get("status") for s in samples],
        "elapsed_ms": [s.get("elapsed_ms") for s in samples],
    }


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
