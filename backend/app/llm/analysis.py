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
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.llm.base import DEFAULT_SETTINGS, LLMProvider, LLMSettings, ProviderError, ToolCall, ToolDispatcher
from app.llm.prompt import INVESTIGATE_PROMPT, SYSTEM_PROMPT
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


@dataclass
class AnalysisOutcome:
    """1.4.0: the parsed result plus what the tool path did (empty otherwise)."""

    result: StructuredResult
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


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


async def _with_backoff(
    call: Callable[[], Awaitable],
    *,
    max_attempts: int,
    max_total_s: float,
    sleep: Callable[[float], Awaitable[None]],
):
    """Run ``call`` retrying retryable ProviderErrors with backoff (the same
    budget rules as ``_analyze_with_backoff``). ``call`` is re-invoked as is,
    so a closure that carries state (the tool transcript) resumes from it."""
    spent = 0.0
    for attempt in range(1, max_attempts + 1):
        try:
            return await call()
        except ProviderError as exc:
            remaining = max_total_s - spent
            if not exc.retryable or attempt == max_attempts or remaining <= 0:
                raise
            delay = min(_backoff_delay(exc, attempt), remaining)
            await sleep(delay)
            spent += delay
    raise AssertionError("unreachable")  # pragma: no cover


async def run_analysis_outcome(
    bundle: dict,
    *,
    provider: LLMProvider,
    model: str,
    settings: LLMSettings = DEFAULT_SETTINGS,
    max_retries: int = 1,
    max_call_attempts: int = MAX_CALL_ATTEMPTS,
    max_backoff_total_s: float = MAX_BACKOFF_TOTAL_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    tools: list[dict] | None = None,
    call_tool: ToolDispatcher | None = None,
) -> AnalysisOutcome:
    """One structured analysis call with ``max_retries`` retries on invalid JSON
    and backoff-retry on transient provider errors (429/5xx).

    With ``tools`` and a provider that supports them (1.4.0), the model runs a
    tool-use conversation; the invalid-JSON correction and transient retries
    continue the *same* transcript, so tool results stay in context and no tool
    call is repeated. Returns an AnalysisOutcome, or raises AnalysisParseError
    (bad JSON) or ProviderError (transient failure that outlasted the backoff).
    """
    base_user = build_user_message(bundle)
    attempts = max_retries + 1
    last_raw: str | None = None
    last_error: Exception | None = None

    supports = getattr(provider, "supports_tools", None)
    use_tools = bool(tools) and call_tool is not None and callable(supports) and supports()
    if not use_tools:
        for attempt in range(attempts):
            user = base_user if attempt == 0 else f"{_RETRY_CORRECTION}\n\n{base_user}"
            last_raw = await _analyze_with_backoff(
                provider, system=SYSTEM_PROMPT, user=user, model=model, settings=settings,
                max_attempts=max_call_attempts, max_total_s=max_backoff_total_s, sleep=sleep,
            )
            try:
                return AnalysisOutcome(result=parse_structured_result(last_raw))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
        raise AnalysisParseError(
            f"LLM returned invalid output after {attempts} attempt(s)",
            attempts=attempts, last_raw=last_raw, last_error=last_error,
        )

    system = f"{SYSTEM_PROMPT}\n\n{INVESTIGATE_PROMPT}"
    state: dict = {"messages": [{"role": "user", "content": base_user}]}
    tool_calls: list[ToolCall] = []
    usage = {"input_tokens": 0, "output_tokens": 0}

    async def one_round():
        # The provider extends state["messages"] in place as the conversation
        # advances, so a transient error after some tool calls leaves their turns
        # in the transcript and the retry resumes from them (no tool is re-run).
        run = await provider.analyze_with_tools(
            system=system, messages=state["messages"], model=model, tools=tools or [],
            call_tool=call_tool, settings=settings, tool_calls=tool_calls,
        )
        state["messages"] = run["messages"]
        for key in usage:
            usage[key] += int((run.get("usage") or {}).get(key) or 0)
        return run["text"]

    for attempt in range(attempts):
        if attempt > 0:
            state["messages"] = [*state["messages"], {"role": "user", "content": _RETRY_CORRECTION}]
        last_raw = await _with_backoff(
            one_round, max_attempts=max_call_attempts, max_total_s=max_backoff_total_s, sleep=sleep,
        )
        try:
            return AnalysisOutcome(result=parse_structured_result(last_raw), tool_calls=tool_calls, usage=usage)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc

    raise AnalysisParseError(
        f"LLM returned invalid output after {attempts} attempt(s)",
        attempts=attempts, last_raw=last_raw, last_error=last_error,
    )


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
    tools: list[dict] | None = None,
    call_tool: ToolDispatcher | None = None,
) -> StructuredResult:
    """``run_analysis_outcome`` for callers that only need the parsed result."""
    outcome = await run_analysis_outcome(
        bundle, provider=provider, model=model, settings=settings, max_retries=max_retries,
        max_call_attempts=max_call_attempts, max_backoff_total_s=max_backoff_total_s, sleep=sleep,
        tools=tools, call_tool=call_tool,
    )
    return outcome.result
