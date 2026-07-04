"""T03 — DNS resolver (spec §3.1).

Scenarios:
  1. Multi-step CNAME chain (www->apex->edgekey->akamaiedge) complete & ordered.
  2. No CNAME -> empty chain, A records present.
  3. NXDOMAIN -> typed error (no library exception leak).
  4. AAAA-only host handled; TTL captured from the answer.
  5. CNAME loop / >10 CNAMEs -> truncated flag, no infinite loop.

All tests use a FakeQuerier — no live DNS. A live smoke test is marked @live.
"""

import json

import pytest

from app.collectors.dns import (
    DnsError,
    DnsNoAnswer,
    DnsNXDomain,
    QueryAnswer,
    resolve_dns,
)


class FakeQuerier:
    """Answers keyed by (name, rdtype). A value may be a QueryAnswer or an
    Exception (raised). Missing keys default to NODATA (DnsNoAnswer)."""

    def __init__(self, answers: dict) -> None:
        self._answers = answers
        self.calls: list[tuple[str, str]] = []

    async def query(self, name: str, rdtype: str) -> QueryAnswer:
        self.calls.append((name, rdtype))
        if (name, rdtype) not in self._answers:
            raise DnsNoAnswer(name, rdtype)
        value = self._answers[(name, rdtype)]
        if isinstance(value, Exception):
            raise value
        return value


# --- Scenario 1 ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_step_cname_chain_ordered():
    q = FakeQuerier(
        {
            ("www.example.com", "CNAME"): QueryAnswer(["apex.example.com."], 300),
            ("apex.example.com", "CNAME"): QueryAnswer(["example.com.edgekey.net."], 300),
            ("example.com.edgekey.net", "CNAME"): QueryAnswer(["e123.akamaiedge.net."], 20),
            ("e123.akamaiedge.net", "A"): QueryAnswer(["23.55.1.1", "23.55.1.2"], 20),
            ("example.com", "NS"): QueryAnswer(["ns1.example.com.", "ns2.example.com."], 3600),
        }
    )
    result = await resolve_dns("www.example.com", querier=q)

    assert [c["name"] for c in result["cname_chain"]] == [
        "www.example.com",
        "apex.example.com",
        "example.com.edgekey.net",
    ]
    assert [c["cname"] for c in result["cname_chain"]] == [
        "apex.example.com",
        "example.com.edgekey.net",
        "e123.akamaiedge.net",
    ]
    assert result["a"] == ["23.55.1.1", "23.55.1.2"]
    assert result["ns"] == ["ns1.example.com", "ns2.example.com"]
    assert result["ttl"] == 20  # A-record ttl
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_result_is_json_serializable():
    q = FakeQuerier(
        {
            ("example.com", "A"): QueryAnswer(["93.184.216.34"], 300),
            ("example.com", "NS"): QueryAnswer(["a.iana-servers.net."], 3600),
        }
    )
    result = await resolve_dns("example.com", querier=q)
    # Round-trips through JSON unchanged (done-criterion: fits dns_json).
    assert json.loads(json.dumps(result)) == result


@pytest.mark.asyncio
async def test_accepts_full_url():
    q = FakeQuerier({("example.com", "A"): QueryAnswer(["93.184.216.34"], 300)})
    result = await resolve_dns("https://example.com/some/path?x=1", querier=q)
    assert result["a"] == ["93.184.216.34"]


# --- Scenario 2 ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_cname_empty_chain_with_a_records():
    q = FakeQuerier(
        {
            ("example.com", "A"): QueryAnswer(["93.184.216.34"], 300),
            ("example.com", "NS"): QueryAnswer(["a.iana-servers.net."], 3600),
        }
    )
    result = await resolve_dns("example.com", querier=q)
    assert result["cname_chain"] == []
    assert result["a"] == ["93.184.216.34"]
    assert result["aaaa"] == []
    assert result["ttl"] == 300


# --- Scenario 3 ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_nxdomain_raises_typed_error():
    q = FakeQuerier({("nope.invalid", "CNAME"): DnsNXDomain("nope.invalid")})
    with pytest.raises(DnsNXDomain) as exc_info:
        await resolve_dns("nope.invalid", querier=q)
    assert exc_info.value.name == "nope.invalid"
    assert isinstance(exc_info.value, DnsError)


# --- Scenario 4 ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_aaaa_only_host_and_ttl():
    q = FakeQuerier(
        {
            # No CNAME, no A -> both NODATA (default). Only AAAA present.
            ("v6.example.com", "AAAA"): QueryAnswer(["2606:2800:220:1:248:1893:25c8:1946"], 120),
            ("example.com", "NS"): QueryAnswer(["ns1.example.com."], 3600),
        }
    )
    result = await resolve_dns("v6.example.com", querier=q)
    assert result["a"] == []
    assert result["aaaa"] == ["2606:2800:220:1:248:1893:25c8:1946"]
    assert result["ttl"] == 120  # falls back to AAAA ttl when no A


# --- Scenario 5 ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_cname_loop_truncated_no_infinite_loop():
    q = FakeQuerier(
        {
            ("a.example.com", "CNAME"): QueryAnswer(["b.example.com."], 300),
            ("b.example.com", "CNAME"): QueryAnswer(["a.example.com."], 300),
        }
    )
    result = await resolve_dns("a.example.com", querier=q)
    assert result["truncated"] is True
    # Stops as soon as it revisits a seen name — finite chain.
    assert len(result["cname_chain"]) == 2
    assert result["cname_chain"][-1]["cname"] == "a.example.com"


@pytest.mark.asyncio
async def test_more_than_max_cnames_truncated():
    # A 15-long CNAME chain c0->c1->...->c15, exceeding MAX_CNAME_HOPS (10).
    answers = {
        (f"c{i}.example.com", "CNAME"): QueryAnswer([f"c{i + 1}.example.com."], 300)
        for i in range(15)
    }
    q = FakeQuerier(answers)
    result = await resolve_dns("c0.example.com", querier=q)
    assert result["truncated"] is True
    assert len(result["cname_chain"]) == 10  # capped at MAX_CNAME_HOPS


# --- Live smoke (excluded by default) ----------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_resolution_example_com():
    result = await resolve_dns("example.com")
    assert result["a"] or result["aaaa"]
    assert json.loads(json.dumps(result)) == result
