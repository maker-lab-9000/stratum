"""T09 — pipeline orchestrator (spec §3, §9).

Scenarios:
  1. Happy path (faked) -> events in order, report done, all JSON columns set.
  2. DNS/warm/traceroute run concurrently (overlapping timestamps).
  3. Traceroute fail -> done + gap; sampler total fail -> error + partial evidence.
  4. LLM fail -> done + degraded verdict, evidence persisted, no crash.
  5. Concurrency 1 -> second job queued, events don't interleave.
  6. Cancellation mid-run -> status error(cancelled); no orphan subprocess.
"""

import asyncio
import time

import pytest

from app.collectors.traceroute import DefaultSubprocessRunner
from app.pipeline.events import JobBus
from app.pipeline.manager import PipelineManager
from app.pipeline.orchestrator import PipelineDeps, run_analysis

URL = "https://www.example-foods.com/"

DNS_OK = {"a": ["23.55.1.1"], "aaaa": [], "cname_chain": [], "ns": ["ns1.x"], "ttl": 300, "truncated": False}
WARM_OK = {"warmed": True, "skipped": False, "error": None, "timing": {"status": 200, "load_ms": 100}}
TRACE_OK = {"tool": "mtr", "target": "t", "port": 443, "timed_out": False, "error": None,
            "hops": [{"n": 1, "ip": "23.55.1.1", "rtt_ms": 1.0, "unresponsive": False}]}
ENRICH_OK = {"hops": [{"n": 1, "ip": "23.55.1.1", "rdns": None, "asn": 20940, "org": "Akamai",
                       "city": "Frankfurt", "rtt_ms": 1.0, "private": False, "unresponsive": False, "hint": None}],
             "geo_available": True, "notes": []}
VERDICT_OK = {"verdict_json": {"cached": True, "confidence": "high", "provider": "Akamai"},
              "llm_json": {"overall_summary": "cached at edge", "security_findings": [], "performance_findings": []}}


def _sample(request=1, age=0, ok=True):
    headers = [["X-Cache", "TCP_HIT from a1"], ["Age", str(age)], ["Cache-Control", "max-age=600"]]
    return {"request": request, "ok": ok, "status": 200 if ok else None, "http_version": "HTTP/2",
            "url": URL, "headers": headers if ok else [], "elapsed_ms": 10.0, "started_at_ms": 0.0,
            "error": None if ok else "timeout"}


def make_deps(*, dns=DNS_OK, warm=WARM_OK, samples=None, traceroute=TRACE_OK,
              enrichment=ENRICH_OK, analyze=VERDICT_OK, sleep=0.0, timeline=None):
    """Build fake PipelineDeps. Any value may be an Exception to raise. analyze
    may be VERDICT_OK, an Exception, or None (LLM-not-configured path)."""
    samples = samples if samples is not None else [_sample(i, 0) for i in range(1, 5)]

    async def rec(name, value):
        if timeline is not None:
            timeline.append((name, "start", time.monotonic()))
        if sleep:
            await asyncio.sleep(sleep)
        if timeline is not None:
            timeline.append((name, "end", time.monotonic()))
        if isinstance(value, Exception):
            raise value
        return value

    async def _dns(url):
        return await rec("dns", dns)

    async def _warm(url, warm_flag):
        return await rec("warm", warm)

    async def _sample_fn(url, options):
        return await rec("sample", samples)

    async def _trace(url):
        return await rec("traceroute", traceroute)

    async def _enrich(hops):
        return await rec("enrich", enrichment)

    analyze_fn = None
    if analyze is not None:
        async def analyze_fn(bundle, provider=None, model=None):  # noqa: F811
            if isinstance(analyze, Exception):
                raise analyze
            return analyze

    return PipelineDeps(_dns, _warm, _sample_fn, _trace, _enrich, analyze_fn)


def _stages(events):
    return [(e["stage"], e["status"]) for e in events]


# --- Scenario 1 ---------------------------------------------------------------

async def test_happy_path(repo):
    report = repo.create(url=URL, provider="fake", model="fake")
    events: list[dict] = []
    await run_analysis(report.id, URL, {"request_count": 4}, repo=repo, emit=events.append, deps=make_deps())

    saved = repo.get(report.id)
    assert saved.status == "done"
    # All JSON columns populated.
    assert saved.dns_json["a"] == ["23.55.1.1"]
    assert len(saved.samples_json) == 4
    assert saved.traceroute_json["hops"][0]["org"] == "Akamai"
    assert saved.verdict_json["cached"] is True
    assert saved.llm_json["overall_summary"]

    stages = _stages(events)
    assert stages[0] == ("pipeline", "running")
    assert stages[-1] == ("pipeline", "done")
    assert events[-1]["terminal"] is True
    # analyze happens after all evidence stages.
    order = [e["stage"] for e in events]
    assert order.index("analyze") > order.index("sample")
    assert order.index("analyze") > order.index("enrich")


# --- Scenario 2 ---------------------------------------------------------------

async def test_dns_warm_traceroute_run_concurrently(repo):
    report = repo.create(url=URL)
    timeline: list[tuple] = []
    await run_analysis(report.id, URL, {}, repo=repo, emit=lambda e: None,
                       deps=make_deps(sleep=0.1, timeline=timeline))

    def interval(name):
        start = next(t for (n, k, t) in timeline if n == name and k == "start")
        end = next(t for (n, k, t) in timeline if n == name and k == "end")
        return start, end

    dns_i, warm_i, trace_i = interval("dns"), interval("warm"), interval("traceroute")

    def overlap(a, b):
        return a[0] < b[1] and b[0] < a[1]

    assert overlap(dns_i, warm_i)
    assert overlap(dns_i, trace_i)
    assert overlap(warm_i, trace_i)


# --- Scenario 3 ---------------------------------------------------------------

async def test_traceroute_failure_continues_to_done(repo):
    report = repo.create(url=URL)
    failed_trace = {"tool": "mtr", "target": "t", "port": 443, "timed_out": False,
                    "error": {"type": "TraceroutePermissionError", "message": "raw socket denied", "hint": "NET_RAW"},
                    "hops": []}
    events: list[dict] = []
    await run_analysis(report.id, URL, {}, repo=repo, emit=events.append,
                       deps=make_deps(traceroute=failed_trace, enrichment={"hops": [], "geo_available": False, "notes": []}))

    saved = repo.get(report.id)
    assert saved.status == "done"  # traceroute is supplementary
    assert saved.traceroute_json["error"]["type"] == "TraceroutePermissionError"
    # Gap surfaced in the persist_evidence event.
    gaps = next(e for e in events if e["stage"] == "persist_evidence")["gaps"]
    assert any(g["stage"] == "traceroute" for g in gaps)


async def test_sampler_total_failure_is_error_with_partial_evidence(repo):
    report = repo.create(url=URL)
    all_failed = [_sample(1, 0, ok=False), _sample(2, 0, ok=False)]
    await run_analysis(report.id, URL, {}, repo=repo, emit=lambda e: None,
                       deps=make_deps(samples=all_failed))

    saved = repo.get(report.id)
    assert saved.status == "error"
    assert "no successful samples" in saved.error
    # Partial evidence still persisted.
    assert saved.dns_json["a"] == ["23.55.1.1"]
    assert saved.traceroute_json is not None
    # LLM never ran.
    assert saved.verdict_json is None


# --- Scenario 4 ---------------------------------------------------------------

async def test_llm_failure_degrades_but_keeps_evidence(repo):
    report = repo.create(url=URL)
    events: list[dict] = []
    await run_analysis(report.id, URL, {}, repo=repo, emit=events.append,
                       deps=make_deps(analyze=RuntimeError("provider 500")))

    saved = repo.get(report.id)
    assert saved.status == "done"  # degraded, not error
    assert saved.verdict_json["status"] == "unavailable"
    assert "RuntimeError" in saved.verdict_json["reason"]
    assert saved.llm_json is None
    # Evidence intact.
    assert len(saved.samples_json) == 4
    assert events[-1]["degraded"] is True


async def test_no_llm_configured_degrades(repo):
    report = repo.create(url=URL)
    await run_analysis(report.id, URL, {}, repo=repo, emit=lambda e: None, deps=make_deps(analyze=None))
    saved = repo.get(report.id)
    assert saved.status == "done"
    assert saved.verdict_json["status"] == "unavailable"
    assert saved.verdict_json["reason"] == "LLM not configured"


# --- Scenario 5 ---------------------------------------------------------------

async def test_concurrency_one_queues_second_job(repo):
    manager = PipelineManager(repo, concurrency=1, deps=make_deps(sleep=0.15))
    a = repo.create(url=URL)
    b = repo.create(url=URL)

    manager.submit(a.id, URL, {})
    manager.submit(b.id, URL, {})

    # While A runs, B is still queued (semaphore held by A).
    await asyncio.sleep(0.05)
    assert repo.get(a.id).status == "running"
    assert repo.get(b.id).status == "queued"

    await manager.wait(a.id)
    await manager.wait(b.id)
    assert repo.get(a.id).status == "done"
    assert repo.get(b.id).status == "done"

    # Events don't interleave: B's first event comes after A's terminal.
    a_terminal_ts = manager.get_bus(a.id).last()["ts"]
    b_first_ts = manager.get_bus(b.id).history[0]["ts"]
    assert b_first_ts >= a_terminal_ts


# --- Scenario 6 ---------------------------------------------------------------

async def test_cancellation_mid_run_sets_error(repo):
    manager = PipelineManager(repo, concurrency=2, deps=make_deps(sleep=2.0))
    report = repo.create(url=URL)
    manager.submit(report.id, URL, {})

    await asyncio.sleep(0.1)  # let it start running
    assert repo.get(report.id).status == "running"
    assert manager.cancel(report.id) is True
    await manager.wait(report.id)

    saved = repo.get(report.id)
    assert saved.status == "error"
    assert saved.error == "cancelled"


async def test_subprocess_killed_on_cancel(monkeypatch):
    """No orphan process: cancelling a run kills the traceroute subprocess."""
    captured = {}
    real_exec = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        proc = await real_exec(*args, **kwargs)
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)

    runner = DefaultSubprocessRunner()
    task = asyncio.create_task(runner.run(["sleep", "30"], 30.0))
    await asyncio.sleep(0.2)  # let the subprocess spawn
    assert captured["proc"].returncode is None  # running

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The runner killed and reaped the child — no orphan.
    assert captured["proc"].returncode is not None


# --- JobBus -------------------------------------------------------------------

async def test_jobbus_replay_and_live():
    bus = JobBus()
    bus.emit({"stage": "pipeline", "status": "running"})

    received: list[dict] = []

    async def consume():
        async for event in bus.subscribe():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let subscriber attach + drain history
    bus.emit({"stage": "dns", "status": "started"})
    bus.emit({"stage": "pipeline", "status": "done", "terminal": True})
    await asyncio.wait_for(task, timeout=1.0)

    stages = [(e["stage"], e["status"]) for e in received]
    assert stages == [("pipeline", "running"), ("dns", "started"), ("pipeline", "done")]


async def test_jobbus_late_subscriber_gets_history_first():
    bus = JobBus()
    bus.emit({"stage": "pipeline", "status": "running"})
    bus.emit({"stage": "pipeline", "status": "done", "terminal": True})

    received = [e async for e in bus.subscribe()]
    assert [e["status"] for e in received] == ["running", "done"]
