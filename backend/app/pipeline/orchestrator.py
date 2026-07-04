"""Analysis pipeline orchestrator (spec §3, §9).

Runs the seven stages for one report, emitting a progress event per stage:

    (DNS ∥ traceroute ∥ (warm → sample))  →  enrich  →  assemble
        →  persist evidence  →  LLM analyze  →  persist verdict

Concurrency: DNS, traceroute, and warm run concurrently (§3); warm precedes the
sampler so headers are read from a warmed cache. Enrichment needs traceroute's
hops; assembly needs everything.

Robustness (§2 guardrail #5 — LLM failure must never lose evidence):
- Collectors that return typed errors in-band (traceroute, warm, sampler) never
  abort the run; their gaps land in the bundle and the report still completes.
- DNS raises on NXDOMAIN — caught here and turned into a DNS gap.
- No successful samples ⇒ report ``error`` (nothing to analyze) but evidence is
  still persisted.
- LLM failure ⇒ report ``done`` with a degraded ``unavailable`` verdict; all
  evidence is already persisted before the LLM runs.

All stage work is injected via ``PipelineDeps`` so tests use fast, deterministic
fakes; ``default_deps()`` wires the real collectors.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.collectors.dns import DnsError, resolve_dns
from app.collectors.enrichment import (
    DnspythonReverseResolver,
    NullGeoProvider,
    enrich_hops,
)
from app.collectors.http_sampler import sample_requests
from app.collectors.traceroute import run_traceroute
from app.collectors.warmer import warm_cache
from app.pipeline.bundle import assemble_bundle


@dataclass
class PipelineDeps:
    """Stage callables with narrowed signatures the orchestrator invokes
    uniformly. Defaults (``default_deps``) bind the real collectors + config;
    tests pass fakes. ``analyze`` is None until the LLM layer (T11–T12) is wired,
    which yields the degraded verdict — never a crash."""

    resolve_dns: Callable[[str], Awaitable[dict]]
    warm_cache: Callable[[str, bool], Awaitable[dict]]
    sample_requests: Callable[[str, dict], Awaitable[list]]
    run_traceroute: Callable[[str], Awaitable[dict]]
    enrich_hops: Callable[[list], Awaitable[dict]]
    analyze: Callable[[dict], Awaitable[dict]] | None = None


def default_deps(
    *,
    geo=None,
    reverse_resolver=None,
    analyze: Callable[[dict], Awaitable[dict]] | None = None,
    warm_timeout_ms: int = 15_000,
    sample_timeout_ms: int = 10_000,
    traceroute_timeout_s: float = 30.0,
) -> PipelineDeps:
    geo = geo or NullGeoProvider()
    reverse_resolver = reverse_resolver or DnspythonReverseResolver()

    async def _dns(url: str) -> dict:
        return await resolve_dns(url)

    async def _warm(url: str, warm: bool) -> dict:
        return await warm_cache(url, warm=warm, timeout_ms=warm_timeout_ms)

    async def _sample(url: str, options: dict) -> list:
        return await sample_requests(
            url,
            request_count=options.get("request_count", 4),
            interval_ms=options.get("interval_ms", 0),
            extra_request_headers=options.get("extra_request_headers"),
            timeout_ms=sample_timeout_ms,
        )

    async def _traceroute(url: str) -> dict:
        return await run_traceroute(url, timeout_s=traceroute_timeout_s)

    async def _enrich(hops: list) -> dict:
        return await enrich_hops(hops, geo=geo, reverse_resolver=reverse_resolver)

    return PipelineDeps(_dns, _warm, _sample, _traceroute, _enrich, analyze)


async def run_analysis(
    report_id: str,
    url: str,
    options: dict,
    *,
    repo,
    emit: Callable[[dict], object],
    deps: PipelineDeps,
    vantage: str | None = None,
) -> None:
    """Execute the pipeline for one report. Updates status in ``repo`` and emits
    progress events. Never raises except to propagate cancellation."""
    emit({"stage": "pipeline", "status": "running"})
    repo.update(report_id, status="running")

    try:
        dns, traceroute, warm, samples = await _collect(url, options, deps, emit)

        emit({"stage": "enrich", "status": "started"})
        enrichment = await deps.enrich_hops(traceroute.get("hops", []))
        emit({"stage": "enrich", "status": "completed", "data": enrichment})

        bundle = assemble_bundle(
            url=url,
            dns=dns,
            samples=samples,
            warm=warm,
            traceroute=traceroute,
            enrichment=enrichment,
            vantage=vantage,
            request_options=options,
        )

        # Persist all evidence verbatim BEFORE the LLM runs — evidence is never
        # lost to an LLM failure (§2 guardrail #5).
        repo.update(
            report_id,
            dns_json=bundle["dns"],
            samples_json=bundle["samples"],
            traceroute_json=bundle["traceroute"],
        )
        emit({"stage": "persist_evidence", "status": "completed", "gaps": bundle["meta"]["gaps"]})

        if _no_successful_samples(samples):
            repo.update(report_id, status="error", error="no successful samples collected")
            emit({"stage": "pipeline", "status": "error", "terminal": True, "error": "no successful samples collected"})
            return

        emit({"stage": "analyze", "status": "started"})
        verdict = await _analyze(bundle, deps.analyze)
        degraded = verdict["verdict_json"].get("status") == "unavailable"
        emit({"stage": "analyze", "status": "degraded" if degraded else "completed", "data": verdict["verdict_json"]})

        repo.update(
            report_id,
            status="done",
            verdict_json=verdict["verdict_json"],
            llm_json=verdict["llm_json"],
        )
        emit({"stage": "pipeline", "status": "done", "terminal": True, "degraded": degraded})

    except asyncio.CancelledError:
        repo.update(report_id, status="error", error="cancelled")
        emit({"stage": "pipeline", "status": "error", "terminal": True, "error": "cancelled"})
        raise
    except Exception as exc:  # noqa: BLE001 — pipeline must not crash the worker
        message = f"{type(exc).__name__}: {exc}"
        repo.update(report_id, status="error", error=message)
        emit({"stage": "pipeline", "status": "error", "terminal": True, "error": message})


async def _collect(url, options, deps, emit):
    """Run DNS ∥ traceroute ∥ (warm→sample) concurrently (spec §3)."""

    async def dns_stage():
        emit({"stage": "dns", "status": "started"})
        try:
            result = await deps.resolve_dns(url)
            emit({"stage": "dns", "status": "completed", "data": result})
            return result
        except DnsError as exc:
            gap = {"error": {"type": type(exc).__name__, "message": str(exc)}}
            emit({"stage": "dns", "status": "failed", "error": str(exc), "data": gap})
            return gap

    async def traceroute_stage():
        emit({"stage": "traceroute", "status": "started"})
        result = await deps.run_traceroute(url)
        status = "failed" if result.get("error") else "completed"
        emit({"stage": "traceroute", "status": status, "data": result})
        return result

    async def warm_then_sample_stage():
        emit({"stage": "warm", "status": "started"})
        warm = await deps.warm_cache(url, options.get("warm", True))
        emit({"stage": "warm", "status": "completed" if warm.get("warmed") or warm.get("skipped") else "failed", "data": warm})
        emit({"stage": "sample", "status": "started"})
        samples = await deps.sample_requests(url, options)
        emit({"stage": "sample", "status": "completed", "data": samples})
        return warm, samples

    dns, traceroute, (warm, samples) = await asyncio.gather(
        dns_stage(), traceroute_stage(), warm_then_sample_stage()
    )
    return dns, traceroute, warm, samples


async def _analyze(bundle: dict, analyze) -> dict:
    """Run the LLM step. Any failure (or no LLM configured) yields the degraded
    'unavailable' verdict — the T14 contract — never a raise."""
    if analyze is None:
        return {"verdict_json": {"status": "unavailable", "reason": "LLM not configured"}, "llm_json": None}
    try:
        result = await analyze(bundle)
        return {"verdict_json": result["verdict_json"], "llm_json": result.get("llm_json")}
    except Exception as exc:  # noqa: BLE001
        return {
            "verdict_json": {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"},
            "llm_json": None,
        }


def _no_successful_samples(samples: list[dict]) -> bool:
    return not samples or all(not s.get("ok") for s in samples)
