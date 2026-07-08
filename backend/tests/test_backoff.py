"""1.0.3 — transient-failure backoff for the analysis call.

A 429/5xx is retried with backoff (honoring Retry-After) up to 3 attempts /
30 s total before falling through to the degraded verdict; non-retryable errors
(auth, bad request) raise immediately. `sleep` is injected so tests never wait.
"""

from __future__ import annotations

import json

import pytest

from app.llm.analysis import run_analysis
from app.llm.base import ProviderError
from app.pipeline.analyze import make_llm_analyze
from app.llm.schema import StructuredResult
from tests.test_analysis import AKAMAI_BUNDLE, VALID_RESULT


class QueueProvider:
    """analyze() yields queued items in order; an Exception item is raised."""

    id = "q"
    name = "Q"

    def __init__(self, items: list) -> None:
        self._items = list(items)
        self.calls = 0

    def static_models(self) -> list[dict]:
        return []

    async def list_models(self) -> list[dict]:
        return []

    async def analyze(self, *, system, user, model, settings):
        self.calls += 1
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _rate_limit(retry_after: float | None = None) -> ProviderError:
    return ProviderError(
        "429", provider="openrouter", retryable=True, kind="rate_limit",
        status_code=429, retry_after=retry_after,
    )


def _run(provider, waits):
    async def _sleep(d):
        waits.append(d)

    return run_analysis(AKAMAI_BUNDLE, provider=provider, model="m", sleep=_sleep)


async def test_retries_transient_then_succeeds():
    waits: list[float] = []
    provider = QueueProvider([_rate_limit(), json.dumps(VALID_RESULT)])
    result = await _run(provider, waits)
    assert isinstance(result, StructuredResult)
    assert provider.calls == 2
    assert waits == [1.0]  # exponential 2^0


async def test_honors_retry_after_header():
    waits: list[float] = []
    provider = QueueProvider([_rate_limit(retry_after=7.0), json.dumps(VALID_RESULT)])
    await _run(provider, waits)
    assert waits == [7.0]


async def test_gives_up_after_max_attempts():
    waits: list[float] = []
    provider = QueueProvider([_rate_limit(), _rate_limit(), _rate_limit()])
    with pytest.raises(ProviderError):
        await _run(provider, waits)
    assert provider.calls == 3  # MAX_CALL_ATTEMPTS
    assert waits == [1.0, 2.0]  # waited between attempts, not after the last


async def test_total_wait_capped_at_30s():
    waits: list[float] = []
    provider = QueueProvider([_rate_limit(retry_after=25.0), _rate_limit(retry_after=25.0), _rate_limit(retry_after=25.0)])
    with pytest.raises(ProviderError):
        await _run(provider, waits)
    assert waits == [25.0, 5.0]  # second wait clamped to the 30 s remaining budget
    assert sum(waits) <= 30.0


async def test_non_retryable_raises_immediately():
    waits: list[float] = []
    auth_err = ProviderError("401", provider="openrouter", retryable=False, kind="auth", status_code=401)
    provider = QueueProvider([auth_err, json.dumps(VALID_RESULT)])
    with pytest.raises(ProviderError):
        await _run(provider, waits)
    assert provider.calls == 1
    assert waits == []


async def test_rate_limit_degrades_with_clear_message():
    # retry_after=0 → retries are instant (no real wait) but still exhaust.
    provider = QueueProvider([_rate_limit(retry_after=0.0), _rate_limit(retry_after=0.0), _rate_limit(retry_after=0.0)])
    analyze = make_llm_analyze(resolver=lambda _n: provider)
    out = await analyze(AKAMAI_BUNDLE, "openrouter", "m")
    assert out["verdict_json"]["status"] == "unavailable"
    assert "rate-limited by provider 'openrouter'" in out["verdict_json"]["reason"]
    assert out["llm_json"] is None
