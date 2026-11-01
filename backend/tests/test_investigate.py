"""The request_page investigation tool (1.4.0): budget, header policy, call log.

No network: ``request_fn`` is a stub shaped like ``http_sampler.one_request``.
"""

from __future__ import annotations

import pytest

from app.pipeline.investigate import (
    BUDGET,
    TOOL_NAME,
    TOOL_SCHEMA,
    Investigation,
)

URL = "https://www.example-foods.com/"


def _canned(index: int, url: str, headers: dict, *, ok: bool = True) -> dict:
    if not ok:
        return {"request": index, "ok": False, "status": None, "http_version": None, "url": url,
                "headers": [], "elapsed_ms": 10.0, "started_at_ms": 0.0, "error": "ReadTimeout: x",
                "peer_ip": None, "timing": {"connect_ms": None, "tls_ms": None, "ttfb_ms": None,
                                             "total_ms": 10.0, "rtt_ms": None}}
    return {"request": index, "ok": True, "status": 200, "http_version": "HTTP/2", "url": url,
            "headers": [["X-Probe-Echo", ", ".join(f"{k}={v}" for k, v in headers.items())], ["Age", "0"]],
            "elapsed_ms": 55.0, "started_at_ms": 1.0, "error": None, "peer_ip": "23.55.1.1",
            "timing": {"connect_ms": 20.0, "tls_ms": 15.0, "ttfb_ms": 50.0, "total_ms": 55.0, "rtt_ms": None}}


class StubRequests:
    def __init__(self, *, fail_on: set[int] | None = None) -> None:
        self.calls: list[dict] = []
        self.fail_on = fail_on or set()

    async def __call__(self, client, url, index, headers, start_ref):
        self.calls.append({"url": url, "index": index, "headers": dict(headers)})
        return _canned(index, url, headers, ok=index not in self.fail_on)


def _inv(stub, **over):
    events: list[dict] = []
    kwargs = dict(url=URL, base_headers={"X-Base": "1"}, edge_rtt_ms=20.0, next_request=6,
                  emit=events.append, request_fn=stub)
    kwargs.update(over)
    return Investigation(**kwargs), events


async def test_call_records_sample_log_and_event():
    stub = StubRequests()
    inv, events = _inv(stub)
    result = await inv.call({"headers": {"Fastly-Debug": "1"}, "reason": "see the tiers"},
                            model_said="Let me check the debug headers.")

    assert stub.calls[0]["index"] == 6
    assert stub.calls[0]["headers"] == {"X-Base": "1", "Fastly-Debug": "1"}
    assert stub.calls[0]["url"] == URL

    assert result["request"] == 6
    assert result["sample"]["probe"] == "investigation"
    assert result["sample"]["investigation"] == {
        "n": 1, "headers": {"Fastly-Debug": "1"}, "cache_bust": False, "reason": "see the tiers"}
    assert result["timing"]["facts"] == ["request 6 ttfb_ms: 50.0", "request 6 server_ms: 30.0"]
    assert inv.samples == [result["sample"]]
    assert inv.remaining() == BUDGET - 1

    entry = inv.log[0]
    assert entry["n"] == 1 and entry["request"] == 6 and entry["refused"] is None
    assert entry["model_said"] == "Let me check the debug headers."
    assert entry["input"] == {"headers": {"Fastly-Debug": "1"}, "reason": "see the tiers"}
    assert entry["sent"] == {"url": URL, "method": "GET",
                             "headers": [["X-Base", "1"], ["Fastly-Debug", "1"]]}
    assert entry["response"]["status"] == 200 and entry["response"]["header_count"] == 2
    assert entry["response"]["peer_ip"] == "23.55.1.1"
    assert entry["returned"] == result
    assert isinstance(entry["asked_at_ms"], int) and entry["answered_at_ms"] >= entry["asked_at_ms"]

    assert events == [{"stage": "investigate", "status": "progress",
                       "data": {"n": 1, "reason": "see the tiers", "header_names": ["Fastly-Debug"],
                                "status_code": 200, "refused": None}}]


async def test_cache_bust_appends_stratum_cb_param():
    stub = StubRequests()
    inv, _ = _inv(stub)
    await inv.call({"headers": {}, "cache_bust": True, "reason": "force a miss"})
    assert "stratum-cb=" in stub.calls[0]["url"]
    assert "stratum-cb=" in inv.log[0]["sent"]["url"]
    assert inv.samples[0]["investigation"]["cache_bust"] is True


async def test_sixth_call_is_refused_without_a_request():
    stub = StubRequests()
    inv, events = _inv(stub)
    for _ in range(BUDGET):
        await inv.call({"headers": {}, "reason": "again"})
    result = await inv.call({"headers": {}, "reason": "once more"})
    assert result["error"].startswith("budget exhausted: 5 investigation requests were made")
    assert len(stub.calls) == BUDGET
    assert len(inv.samples) == BUDGET
    assert len(inv.log) == BUDGET + 1
    assert inv.log[5]["refused"] == "budget" and inv.log[5]["request"] is None
    assert events[-1]["data"]["refused"] == "budget"
    assert [s["request"] for s in inv.samples] == [6, 7, 8, 9, 10]


@pytest.mark.parametrize("name", ["Host", "content-length", "Transfer-Encoding", "Connection"])
async def test_refused_header_names(name):
    stub = StubRequests()
    inv, _ = _inv(stub)
    result = await inv.call({"headers": {name: "x"}, "reason": "r"})
    assert "error" in result and name.lower() in result["error"].lower()
    assert stub.calls == [] and inv.samples == []
    assert inv.log[0]["refused"].startswith("header_policy:")
    assert inv.remaining() == BUDGET  # a refused call costs no budget


async def test_crlf_value_refused():
    stub = StubRequests()
    inv, _ = _inv(stub)
    result = await inv.call({"headers": {"X-A": "1\r\nX-B: 2"}, "reason": "r"})
    assert "error" in result and stub.calls == []


@pytest.mark.parametrize("headers", [["a"], 3, {"a": 1}, {"bad name": "x"}])
async def test_non_object_headers_refused(headers):
    stub = StubRequests()
    inv, _ = _inv(stub)
    result = await inv.call({"headers": headers, "reason": "r"})
    assert "error" in result and stub.calls == []
    assert inv.log[0]["refused"].startswith("header_policy:")


async def test_missing_headers_means_no_extra_headers():
    stub = StubRequests()
    inv, _ = _inv(stub)
    result = await inv.call({"reason": "plain re-request"})
    assert result["request"] == 6
    assert stub.calls[0]["headers"] == {"X-Base": "1"}


async def test_transport_failure_is_a_failed_sample():
    stub = StubRequests(fail_on={6})
    inv, events = _inv(stub)
    result = await inv.call({"headers": {}, "reason": "r"})
    assert result["sample"]["ok"] is False
    assert result["timing"]["ttfb_ms"] is None
    assert inv.samples[0]["ok"] is False
    assert inv.log[0]["response"] == {"error": "ReadTimeout: x"}
    assert events[0]["data"]["status_code"] is None


async def test_header_names_preserve_case_in_sent():
    stub = StubRequests()
    inv, _ = _inv(stub)
    await inv.call({"headers": {"fastly-DEBUG": "1"}, "reason": "r"})
    assert inv.log[0]["sent"]["headers"] == [["X-Base", "1"], ["fastly-DEBUG", "1"]]


async def test_model_header_overrides_base_header_by_name_case_insensitively():
    stub = StubRequests()
    inv, _ = _inv(stub, base_headers={"User-Agent": "stratum"})
    await inv.call({"headers": {"user-agent": "Mozilla/5.0"}, "reason": "r"})
    assert stub.calls[0]["headers"] == {"user-agent": "Mozilla/5.0"}


def test_tool_schema_shape():
    assert TOOL_SCHEMA["name"] == TOOL_NAME == "request_page"
    props = TOOL_SCHEMA["input_schema"]["properties"]
    assert set(props) == {"headers", "cache_bust", "reason"}
    assert TOOL_SCHEMA["input_schema"]["required"] == ["reason"]
    assert props["headers"]["additionalProperties"] == {"type": "string"}
    assert "5" in TOOL_SCHEMA["description"]
