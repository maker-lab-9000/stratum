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

from app.llm.analysis import AnalysisParseError, run_analysis_outcome
from app.llm.base import DEFAULT_SETTINGS, LLMProvider, LLMSettings, ProviderError
from app.llm.registry import get_provider
from app.pipeline.bundle import timing_section
from app.pipeline.investigate import TOOL_SCHEMA, Investigation
from app.pipeline.validator import validate_verdict


def _degraded(reason: str) -> dict:
    return {"verdict_json": {"status": "unavailable", "reason": reason}, "llm_json": None}


def _supports_tools(provider) -> bool:
    supports = getattr(provider, "supports_tools", None)
    return callable(supports) and bool(supports())


def make_llm_analyze(
    *,
    settings: LLMSettings = DEFAULT_SETTINGS,
    resolver: Callable[[str], LLMProvider | None] | None = None,
    investigation_factory: Callable[..., Investigation] = Investigation,
) -> Callable[..., Awaitable[dict]]:
    """Return an `analyze(bundle, provider, model, *, emit=None) -> dict` with
    ``verdict_json`` and ``llm_json``, plus ``samples`` (the bundle's samples
    extended by any investigation requests) when investigate mode was on.

    ``resolver`` maps a provider name to a provider instance (default: the
    env-driven registry). Tests inject a resolver returning a fake provider and
    an ``investigation_factory`` whose requests never touch the network.
    """
    resolve = resolver or (lambda name: get_provider(name))

    async def analyze(bundle: dict, provider: str, model: str, *, emit=None) -> dict:
        prov = resolve(provider)
        if prov is None:
            return _degraded(f"provider '{provider}' is not configured")

        meta = bundle.get("meta") or {}
        options = meta.get("request_options") or {}
        investigate = bool(options.get("investigate"))
        inv: Investigation | None = None
        tools = call_tool = None
        if investigate and _supports_tools(prov):
            samples = bundle.get("samples") or []
            inv = investigation_factory(
                url=meta.get("url") or bundle.get("url") or "",
                base_headers=options.get("extra_request_headers") or {},
                edge_rtt_ms=(bundle.get("timing") or {}).get("edge_rtt_ms"),
                next_request=max([int(s.get("request") or 0) for s in samples] + [0]) + 1,
                emit=emit,
            )
            tools = [TOOL_SCHEMA]

            async def call_tool(name: str, tool_input: dict, model_said: str) -> dict:
                return await inv.call(tool_input, model_said=model_said)

        def extra(payload: dict) -> dict:
            """Add what the pipeline must persist even on a degraded verdict."""
            if not investigate:
                return payload
            all_samples = list(bundle.get("samples") or []) + (inv.samples if inv else [])
            payload["samples"] = all_samples
            llm = payload.get("llm_json") or {}
            llm["investigation_log"] = inv.log if inv else []
            if inv is None:
                llm["investigation"] = {"requested": True, "available": False,
                                        "reason": f"provider '{provider}' has no tool support"}
            payload["llm_json"] = llm
            return payload

        try:
            outcome = await run_analysis_outcome(
                bundle, provider=prov, model=model, settings=settings, tools=tools, call_tool=call_tool,
            )
        except AnalysisParseError as exc:
            return extra(_degraded(f"LLM returned invalid output after {exc.attempts} attempts"))
        except ProviderError as exc:
            if exc.kind == "rate_limit":
                return extra(_degraded(
                    f"rate-limited by provider '{exc.provider}' after retries — "
                    "retry later or use a paid model (free-tier models have low daily caps)"
                ))
            return extra(_degraded(f"{exc.kind} error from provider '{exc.provider}'"))
        finally:
            if inv is not None:
                await inv.aclose()

        # No unvalidated verdict reaches the DB: validate before returning. In
        # investigate mode the bundle grows by the model's requests first, with
        # its timing facts recomputed, so their citations are checkable.
        validated_bundle = bundle
        if inv is not None and inv.samples:
            all_samples = list(bundle.get("samples") or []) + inv.samples
            validated_bundle = {**bundle, "samples": all_samples, "timing": timing_section(all_samples)}
        validated = validate_verdict(outcome.result, validated_bundle)
        llm_json = validated.verdict.model_dump()
        if inv is not None:
            llm_json["usage"] = outcome.usage
        return extra({"verdict_json": validated.verdict_json(), "llm_json": llm_json})

    return analyze
