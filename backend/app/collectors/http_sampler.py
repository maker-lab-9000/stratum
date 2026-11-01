"""HTTP sampler (spec §3.3, §7 options) — deterministic evidence only.

Sends N consecutive raw GET requests at a configurable interval and captures
each response's **full header set verbatim**: original case, wire order, and
duplicate headers all preserved (via httpx's ``.raw``). It records status,
HTTP version, and timing. It makes no judgement about caching or vendors — the
LLM reads the raw headers later (§2).

Policies (documented per T04 scenario 5):
- Redirects are NOT followed: a 3xx is a valid sample recorded with its status
  and headers. We sample the URL exactly as given.
- Any HTTP response (incl. 4xx/5xx) is a successful sample (``ok=True``); only
  transport failures/timeouts yield ``ok=False``. A timeout on one request does
  not abort the run — remaining requests are still attempted (scenario 6).
- No client-side caching (httpx caches nothing; no conditional headers added).

Timing (1.2.0): each sample records a per-phase split (TCP connect, TLS, time to
first byte, total) from httpcore's ``trace`` extension, plus the peer IP the
request actually connected to. With ``cache_bust_probe`` one extra request is
sent to the same URL with a random ``stratum-cb`` query parameter and recorded
as an entry marked ``"probe": "cache_bust"``. These are raw measurements — the
code never decides what a timing means (§2).
"""

from __future__ import annotations

import asyncio
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

DEFAULT_REQUEST_COUNT = 4
DEFAULT_TIMEOUT_MS = 10_000
PROBE_MARKER = "cache_bust"
INVESTIGATION_MARKER = "investigation"  # 1.4.0: a request the model asked for
PROBE_PARAM = "stratum-cb"
RTT_ATTEMPTS = 3
RTT_TIMEOUT_S = 3.0


def is_probe(sample: dict) -> bool:
    """True for the cache-bust probe entry (not one of the N requests)."""
    return isinstance(sample, dict) and sample.get("probe") == PROBE_MARKER


def is_investigation(sample: dict) -> bool:
    """True for a request the model asked for in investigate mode (1.4.0)."""
    return isinstance(sample, dict) and sample.get("probe") == INVESTIGATION_MARKER


def cache_bust_url(url: str) -> str:
    """``url`` with a random ``stratum-cb`` query parameter added."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append((PROBE_PARAM, secrets.token_hex(8)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def sample_requests(
    url: str,
    *,
    request_count: int = DEFAULT_REQUEST_COUNT,
    interval_ms: int = 0,
    extra_request_headers: dict[str, str] | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    cache_bust_probe: bool = False,
) -> list[dict]:
    """Collect ``request_count`` samples. Returns a list serializable into
    ``samples_json`` (spec §6). Never raises for per-request failures — those
    are captured in the sample's ``ok``/``error`` fields."""
    if request_count < 1:
        return []

    headers = dict(extra_request_headers or {})
    timeout = httpx.Timeout(timeout_ms / 1000)
    samples: list[dict] = []
    start_ref = time.perf_counter()

    async with httpx.AsyncClient(
        http2=True, follow_redirects=False, timeout=timeout
    ) as client:
        for index in range(1, request_count + 1):
            if index > 1 and interval_ms > 0:
                await asyncio.sleep(interval_ms / 1000)
            samples.append(await one_request(client, url, index, headers, start_ref))
        await _attach_edge_rtt(samples, url)
        if cache_bust_probe:
            probe = await one_request(
                client, cache_bust_url(url), request_count + 1, headers, start_ref
            )
            probe["probe"] = PROBE_MARKER
            samples.append(probe)

    return samples


async def one_request(
    client: httpx.AsyncClient,
    url: str,
    index: int,
    headers: dict[str, str],
    start_ref: float,
) -> dict:
    started_at_ms = (time.perf_counter() - start_ref) * 1000
    marks: dict[str, float] = {}
    connected: dict[str, str | None] = {}

    async def trace(event: str, info: dict) -> None:
        # httpcore emits "<prefix>.<phase>.started|complete"; keep the first
        # occurrence of each so a retried phase can't stretch the split.
        phase = event.split(".", 1)[-1]
        marks.setdefault(phase, time.perf_counter())
        if phase == "connect_tcp.complete":
            # Read the peer address while the socket is open — a server that
            # closes after responding leaves no address on the stream later.
            connected["peer_ip"] = _address_of(info.get("return_value"))

    start = time.perf_counter()
    try:
        response = await client.get(url, headers=headers, extensions={"trace": trace})
    except httpx.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "request": index,
            "ok": False,
            "status": None,
            "http_version": None,
            "url": url,
            "headers": [],
            "elapsed_ms": round(elapsed_ms, 3),
            "started_at_ms": round(started_at_ms, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "peer_ip": None,
            "timing": _timing(marks, elapsed_ms),
        }

    elapsed_ms = (time.perf_counter() - start) * 1000
    # .raw preserves original case, wire order, and duplicate headers (verbatim).
    raw_headers = [
        [name.decode("latin-1"), value.decode("latin-1")]
        for name, value in response.headers.raw
    ]
    return {
        "request": index,
        "ok": True,
        "status": response.status_code,
        "http_version": response.http_version,
        "url": str(response.url),
        "headers": raw_headers,
        "elapsed_ms": round(elapsed_ms, 3),
        "started_at_ms": round(started_at_ms, 3),
        "error": None,
        "peer_ip": connected.get("peer_ip") or _address_of(response.extensions.get("network_stream")),
        "timing": _timing(marks, elapsed_ms),
    }


def _span(marks: dict[str, float], begin: str, end: str) -> float | None:
    if begin in marks and end in marks:
        return round((marks[end] - marks[begin]) * 1000, 1)
    return None


def _timing(marks: dict[str, float], elapsed_ms: float) -> dict:
    """Per-phase split in ms. connect/TLS are None on a reused connection."""
    return {
        "connect_ms": _span(marks, "connect_tcp.started", "connect_tcp.complete"),
        "tls_ms": _span(marks, "start_tls.started", "start_tls.complete"),
        "ttfb_ms": _span(marks, "send_request_headers.started", "receive_response_headers.complete"),
        "total_ms": round(elapsed_ms, 1),
        "rtt_ms": None,  # set on the first request by _attach_edge_rtt
    }


def _address_of(stream) -> str | None:
    """IP of a network stream's remote end, or None (reused/closed/unknown)."""
    try:
        address = stream.get_extra_info("server_addr") if stream is not None else None
        return str(address[0]) if address else None
    except Exception:  # noqa: BLE001 — a missing peer address is not an error
        return None


async def _attach_edge_rtt(samples: list[dict], url: str) -> None:
    """Edge round trip as a bare TCP connect to the IP the first request reached.

    httpcore's ``connect_tcp`` span also covers DNS resolution, so it can't serve
    as the round trip; connecting straight to the resolved peer IP has no DNS in
    the timed span. Best of ``RTT_ATTEMPTS`` connects; ``None`` if none succeed.
    """
    first = next((s for s in samples if s.get("peer_ip")), None)
    if first is None:
        return
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    best: float | None = None
    for _ in range(RTT_ATTEMPTS):
        rtt = await _tcp_connect_ms(first["peer_ip"], port)
        if rtt is not None and (best is None or rtt < best):
            best = rtt
    first["timing"]["rtt_ms"] = best


async def _tcp_connect_ms(ip: str, port: int) -> float | None:
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), RTT_TIMEOUT_S)
    except (OSError, asyncio.TimeoutError):
        return None
    elapsed = (time.perf_counter() - start) * 1000
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return round(elapsed, 1)


_one_request = one_request  # 1.4.0: public name; alias kept for older imports
