"""The analysis call (spec §5.2, §5.3): bundle -> StructuredResult.

Builds the user message from the evidence bundle, calls the provider, and parses
its raw text strictly (no code-fence stripping — a fenced/prose response is
rejected and retried once, per §5.2 "strict JSON only"). Two failures raise
``AnalysisParseError``, which the degraded path (T14) consumes so evidence is
never lost.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from app.llm.base import DEFAULT_SETTINGS, LLMProvider, LLMSettings, ProviderError
from app.llm.prompt import SYSTEM_PROMPT
from app.llm.schema import StructuredResult

_RETRY_CORRECTION = (
    "Your previous response was not valid JSON matching the schema. "
    "Return ONLY the JSON object — no prose, no markdown code fences."
)

# Transient-failure backoff (v1.0.3). A 429/5xx is retried with backoff (honoring
# Retry-After) before falling through to the degraded verdict — important for
# rate-limited free-tier models. Non-retryable errors (auth, bad request) raise
# immediately. Total wait is capped so a single run never hangs the live view.
MAX_CALL_ATTEMPTS = 3
MAX_BACKOFF_TOTAL_S = 30.0


def _backoff_delay(exc: ProviderError, attempt: int) -> float:
    """Seconds to wait before the next attempt: honor Retry-After, else 2^(n-1)."""
    if exc.retry_after is not None:
        return exc.retry_after
    return float(2 ** (attempt - 1))  # 1, 2, 4, …


class AnalysisParseError(Exception):
    """The LLM returned unparseable/invalid output after the retry."""

    def __init__(self, message: str, *, attempts: int, last_raw: str | None = None,
                 last_error: Exception | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_raw = last_raw
        self.last_error = last_error


def build_user_message(bundle: dict) -> str:
    """The user message is exactly the evidence bundle as JSON — no interpretation
    hints, so the payload carries only raw facts (§2)."""
    return json.dumps(bundle, indent=2, ensure_ascii=False)


def parse_structured_result(raw: str) -> StructuredResult:
    """Strict parse: json.loads (rejects fences/prose) then schema validation."""
    data = json.loads(raw)  # raises JSONDecodeError on fences/prose
    return StructuredResult.model_validate(data)  # raises ValidationError on schema


async def _analyze_with_backoff(
    provider: LLMProvider,
    *,
    system: str,
    user: str,
    model: str,
    settings: LLMSettings,
    max_attempts: int,
    max_total_s: float,
    sleep: Callable[[float], Awaitable[None]],
) -> str:
    """Call ``provider.analyze``, retrying retryable ProviderErrors (429/5xx) with
    backoff up to ``max_attempts`` and ``max_total_s`` total wait. Non-retryable
    errors raise immediately; the last retryable error raises after the budget."""
    spent = 0.0
    for attempt in range(1, max_attempts + 1):
        try:
            return await provider.analyze(system=system, user=user, model=model, settings=settings)
        except ProviderError as exc:
            remaining = max_total_s - spent
            if not exc.retryable or attempt == max_attempts or remaining <= 0:
                raise
            delay = min(_backoff_delay(exc, attempt), remaining)
            await sleep(delay)
            spent += delay
    raise AssertionError("unreachable")  # pragma: no cover


async def run_analysis(
    bundle: dict,
    *,
    provider: LLMProvider,
    model: str,
    settings: LLMSettings = DEFAULT_SETTINGS,
    max_retries: int = 1,
    max_call_attempts: int = MAX_CALL_ATTEMPTS,
    max_backoff_total_s: float = MAX_BACKOFF_TOTAL_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> StructuredResult:
    """One structured analysis call with ``max_retries`` retries on invalid JSON
    and backoff-retry on transient provider errors (429/5xx).

    Returns a validated StructuredResult, or raises AnalysisParseError (bad JSON)
    or ProviderError (transient failure that outlasted the backoff budget).
    """
    base_user = build_user_message(bundle)
    attempts = max_retries + 1
    last_raw: str | None = None
    last_error: Exception | None = None

    for attempt in range(attempts):
        user = base_user if attempt == 0 else f"{_RETRY_CORRECTION}\n\n{base_user}"
        last_raw = await _analyze_with_backoff(
            provider,
            system=SYSTEM_PROMPT,
            user=user,
            model=model,
            settings=settings,
            max_attempts=max_call_attempts,
            max_total_s=max_backoff_total_s,
            sleep=sleep,
        )
        try:
            return parse_structured_result(last_raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc

    raise AnalysisParseError(
        f"LLM returned invalid output after {attempts} attempt(s)",
        attempts=attempts,
        last_raw=last_raw,
        last_error=last_error,
    )
