"""LLM provider abstraction (spec §5.1).

One interface, many providers (T11): `list_models()` and `analyze() -> raw text`
(T12 parses that text into the structured verdict). Keys come from env only and
must never appear in logs, exceptions, or API responses (§10).

Generation settings (temperature, max_tokens) are centralized here. NOTE on
temperature: the current Anthropic models (`claude-opus-4-8`, `claude-sonnet-5`,
…) **reject** the `temperature` parameter with a 400, so the Anthropic adapter
omits it; OpenRouter (OpenAI-compatible) accepts and receives temperature 0.
Determinism there relies on the model plus the retry-on-invalid-JSON guardrail
(§2). See progress.md decisions — this deviates from a literal reading of §5.2.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

import httpx

DEFAULT_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class LLMSettings:
    """Centralized generation settings."""

    temperature: float = 0.0
    max_tokens: int = 8192


DEFAULT_SETTINGS = LLMSettings()


class ProviderError(Exception):
    """Typed provider failure. Carries a retry-ability flag and a coarse kind so
    the caller can distinguish auth (non-retryable) from transient (retryable).
    Messages never include key material."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        retryable: bool,
        kind: str = "error",
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.kind = kind  # auth | rate_limit | transient | invalid_request | error
        self.status_code = status_code
        self.retry_after = retry_after  # seconds from a Retry-After header, if any


def classify_status(status: int) -> tuple[str, bool]:
    """Map an HTTP status to (kind, retryable)."""
    if status in (401, 403):
        return ("auth", False)
    if status == 429:
        return ("rate_limit", True)
    if status >= 500:
        return ("transient", True)
    return ("invalid_request", False)


async def request_json(
    method: str,
    url: str,
    *,
    headers: dict,
    provider: str,
    timeout: float,
    json: dict | None = None,
) -> dict:
    """HTTP request returning parsed JSON, translating failures to ProviderError.

    Never surfaces request headers (which hold the API key) in the error — only
    the status and the provider's own response snippet, which cannot contain our
    key."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, headers=headers, json=json)
    except httpx.HTTPError as exc:
        raise ProviderError(
            f"{provider} connection error: {type(exc).__name__}",
            provider=provider,
            retryable=True,
            kind="transient",
        ) from exc

    if response.status_code >= 400:
        kind, retryable = classify_status(response.status_code)
        raise ProviderError(
            f"{provider} request failed ({response.status_code}): {response.text[:200]}",
            provider=provider,
            retryable=retryable,
            kind=kind,
            status_code=response.status_code,
            retry_after=_parse_retry_after(response.headers.get("retry-after")),
        )
    return response.json()


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header. Only the delta-seconds form is honored
    (the HTTP-date form is ignored — backoff takes over)."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class LLMProvider(abc.ABC):
    """Adding a provider = one subclass + a registry entry (T11 done-criterion)."""

    id: str
    name: str

    @abc.abstractmethod
    def static_models(self) -> list[dict]:
        """Offline fallback model list ([{id, name}, ...]) for GET /api/models."""

    @abc.abstractmethod
    async def list_models(self) -> list[dict]:
        """Live model list; falls back to static_models() on any error."""

    @abc.abstractmethod
    async def analyze(
        self, *, system: str, user: str, model: str, settings: LLMSettings = DEFAULT_SETTINGS
    ) -> str:
        """Run one completion; return the model's raw text (T12 parses it)."""
