"""Runner: every case × every model through the production analysis path.

``analyze`` is the same callable the pipeline uses (``make_llm_analyze``:
provider → run_analysis with JSON retry + 429/5xx backoff → evidence
validator), so each verdict is exactly what a real report would show. Calls run
one at a time — free-tier models rate-limit aggressively.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.llm.prompt import SYSTEM_PROMPT
from evals.case import Case, CaseError, rebuild_bundle
from evals.score import Outcome, evaluate

RUNS_DIR = Path(__file__).parent / "runs"

Analyze = Callable[..., Awaitable[dict]]  # analyze(bundle, provider, model, *, emit=None)
INVESTIGATE_SUFFIX = " +investigate"


class SetupError(Exception):
    """Bad arguments or configuration, detected before any model call."""


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return self.model

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


def parse_model_spec(text: str) -> ModelSpec:
    """``provider:model``, split on the first colon (model ids may contain
    colons, e.g. a ``:free`` suffix)."""
    provider, sep, model = text.partition(":")
    if not sep or not provider.strip() or not model.strip():
        raise SetupError(f"model {text!r} must look like provider:model")
    return ModelSpec(provider.strip(), model.strip())


@dataclass
class EvalRun:
    outcomes: dict[tuple[str, str], Outcome] = field(default_factory=dict)
    records: list[dict] = field(default_factory=list)


async def run_eval(
    cases: Sequence[Case],
    models: Sequence[ModelSpec],
    *,
    analyze: Analyze,
    is_configured: Callable[[str], bool],
    progress: Callable[[str], None] = lambda _: None,
    investigate: bool = False,
) -> EvalRun:
    """With ``investigate`` (1.4.0) every case runs twice per model: ``off``
    (frozen, as always) and ``on`` — the frozen bundle plus **live**
    ``request_page`` calls to the case's URL, labelled ``<model> +investigate``.
    The eval's rule of never touching the target is suspended for those rows
    only; cases record no custom request headers, so the live calls carry only
    the model's."""
    if not models:
        raise SetupError("at least one model is required")
    labels = [m.label for m in models]
    if len(set(labels)) != len(labels):
        raise SetupError(f"duplicate model(s) in {[str(m) for m in models]}")
    unconfigured = sorted({m.provider for m in models if not is_configured(m.provider)})
    if unconfigured:
        raise SetupError(
            f"provider(s) not configured: {unconfigured} — set the API key in .env"
        )

    # Build every bundle before the first (paid) call, so a malformed case is a
    # setup error rather than a crash halfway through the run.
    bundles: dict[str, dict] = {}
    for case in cases:
        try:
            bundles[case.name] = rebuild_bundle(case)
        except Exception as exc:  # noqa: BLE001
            raise CaseError(
                f"case {case.name!r}: cannot rebuild the evidence bundle ({type(exc).__name__}: {exc})"
            ) from exc

    run = EvalRun()
    modes = [False, True] if investigate else [False]
    total = len(cases) * len(models) * len(modes)
    k = 0
    for case in cases:
        bundle = bundles[case.name]
        for spec in models:
            for live in modes:
                k += 1
                label = spec.label + (INVESTIGATE_SUFFIX if live else "")
                progress(f"[{k}/{total}] {case.name} × {label}")
                started = time.perf_counter()
                target = bundle
                if live:
                    meta = {**bundle["meta"], "request_options": {
                        **bundle["meta"].get("request_options", {}),
                        "investigate": True, "extra_request_headers": {}}}
                    target = {**bundle, "meta": meta}
                result: dict = {}
                try:
                    result = await analyze(target, spec.provider, spec.model)
                    verdict_json, llm_json = result["verdict_json"], result.get("llm_json")
                except Exception as exc:  # noqa: BLE001 — one bad call must not stop the run
                    verdict_json = {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}
                    llm_json = None
                run.outcomes[(case.name, label)] = evaluate(case, verdict_json)
                record = {
                    "case": case.name,
                    "provider": spec.provider,
                    "model": spec.model,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                    "verdict_json": verdict_json,
                    "llm_json": llm_json,
                    "investigate": live,
                    "extra_requests": _extra_requests(llm_json),
                    "tokens": _tokens(llm_json),
                }
                if live:
                    record["tool_calls"] = (llm_json or {}).get("investigation_log") or []
                    record["samples"] = result.get("samples") or []
                run.records.append(record)
    return run


def _extra_requests(llm_json: dict | None) -> int:
    """Requests actually made (refused calls don't count)."""
    log = (llm_json or {}).get("investigation_log") or []
    return sum(1 for entry in log if not entry.get("refused"))


def _tokens(llm_json: dict | None) -> dict | None:
    usage = (llm_json or {}).get("usage")
    if not isinstance(usage, dict):
        return None
    return {"input": int(usage.get("input_tokens") or 0), "output": int(usage.get("output_tokens") or 0)}


def row_note(record: dict) -> str:
    """The table note for any row: ``frozen · 12.4k tok · 8 s`` for an off row,
    ``live · 2 req · 12.4k tok · 31 s`` for an investigate row (final review:
    the cost delta the experiment measures must be readable for both)."""
    tokens = record.get("tokens") or {}
    total = tokens.get("input", 0) + tokens.get("output", 0)
    tok = f"{total / 1000:.1f}k tok" if total else "tokens n/a"
    secs = f"{round((record.get('duration_ms') or 0) / 1000)} s"
    if record.get("investigate"):
        return f"live · {record.get('extra_requests', 0)} req · {tok} · {secs}"
    return f"frozen · {tok} · {secs}"


live_note = row_note  # kept for callers of the earlier name


def write_results(
    run: EvalRun,
    models: Sequence[ModelSpec],
    directory: Path = RUNS_DIR,
    *,
    now: datetime,
) -> Path:
    """Full per-call results, for inspecting why a model answered as it did."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps({
        "started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "models": [str(m) for m in models],
        "records": run.records,
    }, indent=2, ensure_ascii=False) + "\n")
    return path
