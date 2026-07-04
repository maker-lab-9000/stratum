"""T06 — TCP traceroute runner (spec §3.4, §9).

Scenarios:
  1. Parse recorded mtr --json and tcptraceroute outputs into normalized hops.
  2. `* * *` hops -> unresponsive: true, no fake IP.
  3. Binary missing -> typed TracerouteUnavailable + remediation hint, graceful.
  4. Subprocess hang -> killed at timeout, partial hops returned if any.
  5. Duplicate final-hop lines collapse to one hop with best RTT.

Done-criterion: with no privileges an analysis still completes with
traceroute_json = typed error + empty hops.
"""

import json
from pathlib import Path

import pytest

from app.collectors.traceroute import (
    RunResult,
    TracerouteError,
    parse_mtr_json,
    parse_tcptraceroute,
    run_traceroute,
)

FIXTURES = Path(__file__).parent / "fixtures" / "traceroute"


class FakeRunner:
    """Returns a canned RunResult, or raises a preset exception (e.g.
    FileNotFoundError for a missing binary)."""

    def __init__(self, result: RunResult | None = None, raise_exc: Exception | None = None):
        self._result = result
        self._raise = raise_exc
        self.argv: list[str] | None = None

    async def run(self, argv, timeout_s):
        self.argv = argv
        if self._raise is not None:
            raise self._raise
        return self._result


# --- Scenario 1 + 2 -----------------------------------------------------------

def test_parse_mtr_json_fixture():
    hops = parse_mtr_json((FIXTURES / "mtr_route.json").read_text())
    assert [h["n"] for h in hops] == [1, 2, 3, 4, 5, 6]
    # Best RTT is used.
    assert hops[0]["ip"] == "192.168.1.1" and hops[0]["rtt_ms"] == 0.7
    # Scenario 2: unresponsive hop -> no fake IP.
    assert hops[2]["unresponsive"] is True
    assert hops[2]["ip"] is None
    assert hops[2]["rtt_ms"] is None
    assert hops[-1]["ip"] == "23.55.1.1"


def test_parse_tcptraceroute_fixture():
    hops = parse_tcptraceroute((FIXTURES / "tcptraceroute_route.txt").read_text())
    # Scenario 5: hops 6 & 7 (same dest IP) collapse into one -> 6 hops total.
    assert len(hops) == 6
    assert [h["n"] for h in hops] == [1, 2, 3, 4, 5, 6]
    # Scenario 2: `* * *` -> unresponsive, no IP.
    assert hops[2]["unresponsive"] is True and hops[2]["ip"] is None
    # A line with a `*` probe still yields the responsive IP + min of real RTTs.
    assert hops[4]["ip"] == "72.52.92.14" and hops[4]["rtt_ms"] == 14.1
    # Scenario 5: collapsed final hop keeps best (min) RTT across both lines.
    assert hops[5]["ip"] == "23.55.1.1"
    assert hops[5]["rtt_ms"] == 14.9


def test_parsers_produce_json_serializable_hops():
    hops = parse_mtr_json((FIXTURES / "mtr_route.json").read_text())
    assert json.loads(json.dumps(hops)) == hops


# --- Scenario 3 ---------------------------------------------------------------

async def test_binary_missing_returns_typed_unavailable():
    runner = FakeRunner(raise_exc=FileNotFoundError("mtr"))
    result = await run_traceroute("example.com", tool="mtr", runner=runner)

    assert result["hops"] == []
    assert result["error"]["type"] == "TracerouteUnavailable"
    assert result["error"]["hint"]  # remediation present
    assert "NET_RAW" in result["error"]["hint"]
    # Still a complete, serializable evidence record.
    assert json.loads(json.dumps(result)) == result


async def test_no_tool_found_is_unavailable():
    # An unknown tool name selects nothing -> unavailable, never crashes.
    result = await run_traceroute("example.com", tool="does-not-exist", runner=FakeRunner())
    assert result["error"]["type"] == "TracerouteUnavailable"
    assert result["hops"] == []


# --- permission (done-criterion: no privileges still completes) ---------------

async def test_permission_error_surfaced_with_net_raw_hint():
    runner = FakeRunner(
        RunResult(stdout="", stderr="tcptraceroute: Operation not permitted", returncode=1, timed_out=False)
    )
    result = await run_traceroute("example.com", tool="tcptraceroute", runner=runner)
    assert result["error"]["type"] == "TraceroutePermissionError"
    assert "NET_RAW" in result["error"]["hint"]
    assert result["hops"] == []


async def test_mtr_no_raw_socket_stderr_is_permission_error():
    # Real mtr phrasing observed when raw sockets are denied (e.g. Docker without
    # NET_RAW / unprivileged macOS) — must classify as a permission error.
    stderr = (
        "mtr-packet: Failure to open IPv4 sockets\n"
        "mtr-packet: Failure to open IPv6 sockets\n"
        "mtr: Failure to start mtr-packet: Invalid argument\n"
    )
    runner = FakeRunner(RunResult(stdout="", stderr=stderr, returncode=1, timed_out=False))
    result = await run_traceroute("example.com", tool="mtr", runner=runner)
    assert result["error"]["type"] == "TraceroutePermissionError"
    assert "NET_RAW" in result["error"]["hint"]


# --- Scenario 4 ---------------------------------------------------------------

async def test_timeout_with_partial_hops_returns_them():
    partial = " 1  192.168.1.1  0.8 ms\n 2  100.64.0.1  8.1 ms\n"
    runner = FakeRunner(RunResult(stdout=partial, stderr="", returncode=None, timed_out=True))
    result = await run_traceroute("example.com", tool="tcptraceroute", runner=runner)

    assert result["error"] is None
    assert result["timed_out"] is True
    assert [h["ip"] for h in result["hops"]] == ["192.168.1.1", "100.64.0.1"]


async def test_timeout_with_no_hops_is_typed_error():
    runner = FakeRunner(RunResult(stdout="", stderr="", returncode=None, timed_out=True))
    result = await run_traceroute("example.com", tool="mtr", runner=runner)
    assert result["error"]["type"] == "TracerouteTimeout"
    assert result["hops"] == []


# --- argv / target ------------------------------------------------------------

async def test_argv_targets_tcp_port_443():
    runner = FakeRunner(RunResult(stdout="", stderr="", returncode=0, timed_out=False))
    await run_traceroute("https://www.example.com/path", tool="mtr", runner=runner)
    assert runner.argv[:1] == ["mtr"]
    assert "-T" in runner.argv and "-P" in runner.argv
    assert "443" in runner.argv
    # URL reduced to bare host.
    assert runner.argv[-1] == "www.example.com"


# --- typed error object -------------------------------------------------------

def test_error_to_dict_shape():
    err = TracerouteError("boom", hint="do x")
    assert err.to_dict() == {"type": "TracerouteError", "message": "boom", "hint": "do x"}


# --- live smoke (excluded by default; needs mtr + raw-socket privileges) ------

@pytest.mark.live
async def test_live_traceroute_returns_record():
    result = await run_traceroute("example.com", count=1, timeout_s=20)
    # Either we got hops, or a typed error (e.g. permission) — both are valid,
    # complete, serializable records. What matters: it never raised.
    assert "hops" in result and "error" in result
    assert json.loads(json.dumps(result)) == result
