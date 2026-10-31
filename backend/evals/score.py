"""Scoring: resolve the model's serving layer and chain, match them against the
operator's answer key.

Everything is read from the *validated* verdict (what a report shows). Layer
matching is by keyword (any-of substring over name + vendor + cache type)
and/or role — never by exact name, so a correct answer worded differently is
not marked wrong.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from evals.case import Case, Expected, LayerSpec

NONE_TEXT = "—"


@dataclass(frozen=True)
class Outcome:
    """One case × model result. ``*_ok is None`` means that dimension is not
    scored (no expectation for it)."""

    serving_text: str
    chain_text: str
    serving_ok: bool | None
    chain_ok: bool | None
    unverified: int


def layer_matches(spec: LayerSpec, layer: dict) -> bool:
    if spec.role and layer.get("role") not in spec.role:
        return False
    if spec.match:
        text = " ".join(
            str(layer.get(key) or "") for key in ("layer_name", "vendor", "cache_type")
        ).lower()
        if not any(keyword in text for keyword in spec.match):
            return False
    return True


def resolve_serving(verdict: dict) -> dict | None:
    """Mirror the report UI (frontend serving.ts findServingIndex): the layer
    named by ``serving_layer``, else the first HIT, else none."""
    layers = verdict.get("layers") or []
    name = verdict.get("serving_layer")
    for layer in layers:
        if name and layer.get("layer_name") == name:
            return layer
    for layer in layers:
        if layer.get("state") == "HIT":
            return layer
    return None


def actual_chain(verdict: dict) -> list[dict]:
    """The model's layers user → origin, without the client itself."""
    return [layer for layer in verdict.get("layers") or [] if layer.get("role") != "client"]


def chain_matches(expected: Sequence[LayerSpec], actual: Sequence[dict]) -> bool:
    """Order-preserving alignment: every actual layer is consumed by one
    expected entry it matches; optional expected entries may be skipped."""
    return _align(tuple(expected), tuple(actual), 0, 0)


def _align(exp: tuple, act: tuple, i: int, j: int) -> bool:
    if j == len(act):
        return all(e.optional for e in exp[i:])
    if i == len(exp):
        return False
    if exp[i].optional and _align(exp, act, i + 1, j):
        return True
    return layer_matches(exp[i], act[j]) and _align(exp, act, i + 1, j + 1)


def _layer_name(layer: dict) -> str:
    return str(layer.get("layer_name") or layer.get("vendor") or "?")


def evaluate(case: Case, verdict_json: dict) -> Outcome:
    expected = case.expected
    wants_serving = expected is not None and expected.serving is not None
    wants_chain = expected is not None and expected.chain is not None

    if verdict_json.get("status") == "unavailable":
        text = f"degraded: {verdict_json.get('reason') or 'unknown reason'}"
        return Outcome(
            serving_text=text,
            chain_text=text,
            serving_ok=False if wants_serving else None,
            chain_ok=False if wants_chain else None,
            unverified=0,
        )

    serving = resolve_serving(verdict_json)
    chain = actual_chain(verdict_json)
    serving_text = (
        f"{_layer_name(serving)} ({serving.get('state', '?')})" if serving else NONE_TEXT
    )
    links = " → ".join(f"{_layer_name(l)} [{l.get('state', '?')}]" for l in chain)
    count = verdict_json.get("layer_count_to_origin")
    chain_text = f"{links or NONE_TEXT} · {count if count is not None else '?'} caching"

    flags = (verdict_json.get("validation") or {}).get("flags") or []
    return Outcome(
        serving_text=serving_text,
        chain_text=chain_text,
        serving_ok=(serving is not None and layer_matches(expected.serving, serving))
        if wants_serving else None,
        chain_ok=chain_matches(expected.chain, chain) if wants_chain else None,
        unverified=len(flags),
    )


def expected_texts(expected: Expected | None) -> tuple[str, str]:
    """(serving, chain) display text for the expected row."""
    if expected is None:
        return NONE_TEXT, NONE_TEXT
    serving = expected.serving.label if expected.serving else NONE_TEXT
    chain = (
        " → ".join(f"{s.label}{'?' if s.optional else ''}" for s in expected.chain)
        if expected.chain else NONE_TEXT
    )
    return serving, chain
