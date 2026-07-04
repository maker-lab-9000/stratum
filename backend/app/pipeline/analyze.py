"""Wires the LLM analysis step into the pipeline (T14).

Builds the `analyze(bundle, provider, model)` callable the orchestrator calls:
resolve provider → run_analysis (T12) → validate_verdict (T13) → dict. Any
failure (parse error, provider error, unknown provider) returns the degraded
`{"status": "unavailable", "reason": ...}` verdict instead of raising, so
evidence is never lost and no job wedges in `running` (§2 guardrail #5, §5.2
failure paragraph). This is where "no unvalidated verdict reaches the DB" is
enforced: a successful verdict always passes through the validator first.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.llm.analysis import AnalysisParseError, run_analysis
from app.llm.base import DEFAULT_SETTINGS, LLMProvider, LLMSettings, ProviderError
from app.llm.registry import get_provider
from app.pipeline.validator import validate_verdict


def _degraded(reason: str) -> dict:
    return {"verdict_json": {"status": "unavailable", "reason": reason}, "llm_json": None}


def make_llm_analyze(
    *,
    settings: LLMSettings = DEFAULT_SETTINGS,
    resolver: Callable[[str], LLMProvider | None] | None = None,
) -> Callable[[dict, str, str], Awaitable[dict]]:
    """Return an `analyze(bundle, provider, model) -> {"verdict_json","llm_json"}`.

    ``resolver`` maps a provider name to a provider instance (default: the
    env-driven registry). Tests inject a resolver returning a fake provider.
    """
    resolve = resolver or (lambda name: get_provider(name))

    async def analyze(bundle: dict, provider: str, model: str) -> dict:
        prov = resolve(provider)
        if prov is None:
            return _degraded(f"provider '{provider}' is not configured")
        try:
            result = await run_analysis(bundle, provider=prov, model=model, settings=settings)
        except AnalysisParseError as exc:
            return _degraded(f"LLM returned invalid output after {exc.attempts} attempts")
        except ProviderError as exc:
            return _degraded(f"{exc.kind} error from provider '{exc.provider}'")

        # No unvalidated verdict reaches the DB: validate before returning.
        validated = validate_verdict(result, bundle)
        return {
            "verdict_json": validated.verdict_json(),
            "llm_json": validated.verdict.model_dump(),
        }

    return analyze
