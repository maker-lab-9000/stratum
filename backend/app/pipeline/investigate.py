"""The ``request_page`` investigation tool (1.4.0, design
``docs/superpowers/specs/2026-11-01-investigate-mode-design.md``).

In investigate mode the model may ask for the analysed URL again, up to
``BUDGET`` times, with request headers of its choosing. This module is the
deterministic half: it validates the model's input, performs the request
verbatim through the sampler's request function, tags the sample, keeps the
call log and the budget, and hands the raw result back. It never reads what a
response means (§2): which header to send for which vendor is the prompt's
knowledge, and what the reply shows is the model's reading.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable

import httpx

from app.collectors.http_sampler import (
    DEFAULT_TIMEOUT_MS,
    INVESTIGATION_MARKER,
    cache_bust_url,
    one_request,
)
from app.pipeline.bundle import sample_timing_facts

logger = logging.getLogger(__name__)

BUDGET = 5
TOOL_NAME = "request_page"
REFUSED_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection"})
_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")  # RFC 7230 header-name token

TOOL_SCHEMA: dict = {
    "name": TOOL_NAME,
    "description": (
        f"Request the analysed page URL again, once, with extra request headers of your "
        f"choosing (a vendor debug header, a different User-Agent, Cache-Control: no-cache) "
        f"and optionally a random cache-busting query parameter. Returns the response "
        f"status, headers (verbatim) and timing as a new sample. At most {BUDGET} calls per "
        f"analysis; the URL cannot be changed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "headers": {
                "type": "object",
                "description": "Request headers to add or override, name → value.",
                "additionalProperties": {"type": "string"},
            },
            "cache_bust": {
                "type": "boolean",
                "description": "Append a random query parameter so caches keyed on the URL miss.",
                "default": False,
            },
            "reason": {
                "type": "string",
                "description": "One sentence: what this request should settle.",
            },
        },
        "required": ["reason"],
    },
}

RequestFn = Callable[..., Awaitable[dict]]
REDACTED = "<from analysis options>"


def _failed_sample(index: int, url: str, exc: Exception) -> dict:
    return {"request": index, "ok": False, "status": None, "http_version": None, "url": url,
            "headers": [], "elapsed_ms": 0.0, "started_at_ms": None,
            "error": f"{type(exc).__name__}: {exc}", "peer_ip": None,
            "timing": {"connect_ms": None, "tls_ms": None, "ttfb_ms": None, "total_ms": None, "rtt_ms": None}}


class Investigation:
    """Per-analysis state for the tool: budget, samples, call log, one client."""

    def __init__(
        self,
        *,
        url: str,
        base_headers: dict[str, str] | None,
        edge_rtt_ms: float | None,
        next_request: int,
        emit: Callable[[dict], object] | None = None,
        request_fn: RequestFn = one_request,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._url = url
        self._base = dict(base_headers or {})
        self._edge_rtt = edge_rtt_ms
        self._next_request = next_request
        self._emit = emit
        self._request = request_fn
        self._timeout = timeout_ms
        self._clock = clock
        self._client: httpx.AsyncClient | None = None
        self._start_ref = time.perf_counter()
        self.samples: list[dict] = []
        self.log: list[dict] = []
        self._calls = 0  # tool calls seen, refused ones included
        self.made = 0  # requests actually sent

    def remaining(self) -> int:
        return BUDGET - self.made

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def call(self, tool_input: dict, *, model_said: str = "") -> dict:
        """Run one tool call. Returns the result handed back to the model; never
        raises for a bad input — refusals are results the model can read."""
        self._calls += 1
        asked = int(self._clock() * 1000)
        entry: dict = {
            "n": self._calls,
            "request": None,
            "asked_at_ms": asked,
            "answered_at_ms": None,
            "model_said": model_said or "",
            "input": tool_input if isinstance(tool_input, dict) else {"raw": tool_input},
            "sent": None,
            "response": None,
            "returned": None,
            "refused": None,
        }
        self.log.append(entry)

        headers_in = tool_input.get("headers") if isinstance(tool_input, dict) else None
        reason = str(tool_input.get("reason", "")) if isinstance(tool_input, dict) else ""
        cache_bust = bool(tool_input.get("cache_bust", False)) if isinstance(tool_input, dict) else False

        policy_error = _header_policy_error(headers_in)
        if policy_error is not None:
            return self._refuse(entry, f"header_policy: {policy_error}", reason,
                                {"error": f"request refused: {policy_error}"})
        if self.made >= BUDGET:
            return self._refuse(
                entry, "budget", reason,
                {"error": f"budget exhausted: {BUDGET} investigation requests were made; "
                          "conclude with the evidence you have"},
            )

        model_headers: dict[str, str] = dict(headers_in or {})
        merged = _merge_headers(self._base, model_headers)
        url = cache_bust_url(self._url) if cache_bust else self._url
        index = self._next_request
        self._next_request += 1
        self.made += 1

        logger.info("investigate %d: request %d, headers %s%s", self._calls, index,
                    sorted(model_headers), ", cache-bust" if cache_bust else "")
        try:
            sample = await self._request(self._client_or_open(), url, index, merged, self._start_ref)
        except Exception as exc:  # noqa: BLE001 — a request that cannot be built is a failed sample, never a crash
            sample = _failed_sample(index, url, exc)
        sample["probe"] = INVESTIGATION_MARKER
        # n is the call number (refusals included), the same number the log and
        # the live view use for this call.
        sample["investigation"] = {"n": self._calls, "headers": model_headers,
                                   "cache_bust": cache_bust, "reason": reason}
        self.samples.append(sample)

        result = {"request": index, "sample": sample,
                  "timing": sample_timing_facts(sample, self._edge_rtt)}
        entry["request"] = index
        # The persisted record keeps the operator's own header values out (a
        # staging cookie or token from the analysis options was never stored
        # before); names stay, and the model's values are verbatim.
        entry["sent"] = {"url": url, "method": "GET",
                         "headers": [[k, v if k in model_headers else REDACTED] for k, v in merged.items()]}
        entry["response"] = (
            {"error": sample.get("error")} if not sample.get("ok") else {
                "status": sample.get("status"), "http_version": sample.get("http_version"),
                "peer_ip": sample.get("peer_ip"), "timing": sample.get("timing"),
                "header_count": len(sample.get("headers") or []),
            }
        )
        entry["returned"] = result
        entry["answered_at_ms"] = int(self._clock() * 1000)
        self._emit_event(self._calls, reason, sorted(model_headers), sample.get("status"), None)
        return result

    # -- helpers --------------------------------------------------------------

    def _client_or_open(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                http2=True, follow_redirects=False, timeout=httpx.Timeout(self._timeout / 1000)
            )
        return self._client

    def _refuse(self, entry: dict, refused: str, reason: str, result: dict) -> dict:
        entry["refused"] = refused
        entry["returned"] = result
        entry["answered_at_ms"] = int(self._clock() * 1000)
        names = sorted(entry["input"].get("headers") or {}) if isinstance(entry["input"].get("headers"), dict) else []
        logger.info("investigate %d: refused (%s)", entry["n"], refused)
        self._emit_event(entry["n"], reason, names, None, refused)
        return result

    def _emit_event(self, n: int, reason: str, names: list[str], status: int | None, refused: str | None) -> None:
        if self._emit is not None:
            self._emit({"stage": "investigate", "status": "progress",
                        "data": {"n": n, "reason": reason, "header_names": names,
                                 "status_code": status, "refused": refused}})


def _header_policy_error(headers) -> str | None:
    """None when ``headers`` is acceptable (absent, or a flat name → string map
    with token names, no CR/LF, none of the refused names)."""
    if headers is None:
        return None
    if not isinstance(headers, dict):
        return "headers must be an object of header name to string value"
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            return "headers must be an object of header name to string value"
        if not _TOKEN.match(name):
            return f"invalid header name {name!r}"
        if "\r" in value or "\n" in value:
            return f"header {name!r} value must not contain CR or LF"
        if not all(32 <= ord(ch) < 127 or ch == "\t" for ch in value):
            return f"header {name!r} value must be printable ASCII"
        if name.lower() in REFUSED_HEADERS:
            return f"header {name!r} cannot be set"
    return None


def _merge_headers(base: dict[str, str], override: dict[str, str]) -> dict[str, str]:
    """Base headers with the model's applied over them, matched by name
    case-insensitively; the model's spelling wins for an overridden name."""
    lowered = {k.lower() for k in override}
    merged = {k: v for k, v in base.items() if k.lower() not in lowered}
    merged.update(override)
    return merged
