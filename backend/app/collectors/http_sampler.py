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
"""

from __future__ import annotations

import asyncio
import time

import httpx

DEFAULT_REQUEST_COUNT = 4
DEFAULT_TIMEOUT_MS = 10_000


async def sample_requests(
    url: str,
    *,
    request_count: int = DEFAULT_REQUEST_COUNT,
    interval_ms: int = 0,
    extra_request_headers: dict[str, str] | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
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
            samples.append(await _one_request(client, url, index, headers, start_ref))

    return samples


async def _one_request(
    client: httpx.AsyncClient,
    url: str,
    index: int,
    headers: dict[str, str],
    start_ref: float,
) -> dict:
    started_at_ms = (time.perf_counter() - start_ref) * 1000
    start = time.perf_counter()
    try:
        response = await client.get(url, headers=headers)
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
    }
