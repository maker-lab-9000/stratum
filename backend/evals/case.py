"""Case files: load, validate, and rebuild the evidence bundle.

A case is one frozen report (DNS, samples, traceroute — verbatim) plus an
optional answer key the operator writes from inside knowledge of the setup.
All vendor vocabulary lives in the case data; this module only checks shape.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from app.llm.schema import Role
from app.pipeline.bundle import assemble_bundle

CASES_DIR = Path(__file__).parent / "cases"
NAME_RE = re.compile(r"^[a-z0-9-]+$")
_ROLES = set(get_args(Role))
_CASE_KEYS = {"name", "url", "source", "evidence", "original_verdict", "expected"}
_EXPECTED_KEYS = {"serving", "chain", "notes"}
_SPEC_KEYS = {"label", "match", "role", "optional"}


class CaseError(ValueError):
    """A case file is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class LayerSpec:
    """How the operator describes one layer: a display label plus keyword
    (any-of substring) and/or role criteria."""

    label: str
    match: tuple[str, ...] = ()
    role: tuple[str, ...] = ()
    optional: bool = False


@dataclass(frozen=True)
class Expected:
    serving: LayerSpec | None
    chain: tuple[LayerSpec, ...] | None
    notes: str | None


@dataclass(frozen=True)
class Case:
    name: str
    url: str
    source: dict
    evidence: dict
    original_verdict: dict | None
    expected: Expected | None


def parse_case(data: dict, *, origin: str = "<case>") -> Case:
    """Validate a case-file dict. Every error message starts with ``origin``."""

    def fail(message: str) -> CaseError:
        return CaseError(f"{origin}: {message}")

    if not isinstance(data, dict):
        raise fail("case file must be a JSON object")
    _reject_unknown(data, _CASE_KEYS, "case", fail)
    name = data.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise fail(f"name {name!r} must match {NAME_RE.pattern}")
    url = data.get("url")
    if not isinstance(url, str) or not url:
        raise fail("url is required")
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        raise fail("evidence is required (dns, samples, traceroute)")
    _check_evidence(evidence, fail)
    source = data.get("source") or {}
    if not isinstance(source, dict):
        raise fail("source must be an object")
    original = data.get("original_verdict")
    if original is not None and not isinstance(original, dict):
        raise fail("original_verdict must be an object or null")

    return Case(
        name=name,
        url=url,
        source=source,
        evidence=evidence,
        original_verdict=original,
        expected=_parse_expected(data.get("expected"), fail),
    )


def _parse_expected(raw, fail) -> Expected | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise fail("expected must be an object or null")
    _reject_unknown(raw, _EXPECTED_KEYS, "expected", fail)
    serving = None
    if raw.get("serving") is not None:
        serving = _parse_spec(raw["serving"], "expected.serving", fail, allow_optional=False)
    chain = None
    if raw.get("chain") is not None:
        if not isinstance(raw["chain"], list) or not raw["chain"]:
            raise fail("expected.chain must be a non-empty list")
        chain = tuple(
            _parse_spec(entry, f"expected.chain[{i}]", fail, allow_optional=True)
            for i, entry in enumerate(raw["chain"])
        )
    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise fail("expected.notes must be a string")
    return Expected(serving=serving, chain=chain, notes=notes)


def _parse_spec(raw, where: str, fail, *, allow_optional: bool) -> LayerSpec:
    if not isinstance(raw, dict):
        raise fail(f"{where} must be an object")
    _reject_unknown(raw, _SPEC_KEYS, where, fail)
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        raise fail(f"{where}.label is required")
    match = _string_list(raw.get("match"), f"{where}.match", fail)
    role = _string_list(raw.get("role"), f"{where}.role", fail)
    if not match and not role:
        raise fail(f"{where} needs at least one of 'match' or 'role'")
    unknown = [r for r in role if r not in _ROLES]
    if unknown:
        raise fail(f"{where}.role has unknown value(s) {unknown}; allowed: {sorted(_ROLES)}")
    optional = raw.get("optional", False)
    if not isinstance(optional, bool):
        raise fail(f"{where}.optional must be true or false")
    if optional and not allow_optional:
        raise fail(f"{where} cannot be optional")
    return LayerSpec(
        label=label,
        match=tuple(m.lower() for m in match),
        role=tuple(role),
        optional=optional,
    )


def _reject_unknown(raw: dict, allowed: set[str], where: str, fail) -> None:
    """Typos must fail loudly: an ignored key silently changes the score."""
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise fail(f"{where} has unknown key(s) {unknown}; allowed: {sorted(allowed)}")


def _check_evidence(evidence: dict, fail) -> None:
    """Shape check so a malformed case fails at load, never mid-run."""
    for key in ("dns", "traceroute"):
        if evidence.get(key) is not None and not isinstance(evidence[key], dict):
            raise fail(f"evidence.{key} must be an object or null")
    samples = evidence.get("samples")
    if not isinstance(samples, list):
        raise fail("evidence.samples must be a list")
    for i, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise fail(f"evidence.samples[{i}] must be an object")
        headers = sample.get("headers", [])
        if not isinstance(headers, list) or not all(
            isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) for x in pair)
            for pair in headers
        ):
            raise fail(f"evidence.samples[{i}].headers must be a list of [name, value] pairs")


def _string_list(raw, where: str, fail) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(x, str) and x for x in raw):
        raise fail(f"{where} must be a list of non-empty strings")
    return raw


def load_case(path: Path) -> Case:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseError(f"{path}: cannot read case file ({exc})") from exc
    case = parse_case(data, origin=str(path))
    if case.name != Path(path).stem:
        raise CaseError(f"{path}: name {case.name!r} must match the file name ({Path(path).stem!r})")
    return case


def load_cases(directory: Path = CASES_DIR, names: Sequence[str] | None = None) -> list[Case]:
    """All cases in ``directory`` sorted by name, or just ``names``."""
    directory = Path(directory)
    if names:
        names = list(dict.fromkeys(names))  # repeated --case counts once
        missing = [n for n in names if not (directory / f"{n}.json").is_file()]
        if missing:
            raise CaseError(f"unknown case(s) {missing} in {directory}")
        paths = [directory / f"{n}.json" for n in names]
    else:
        paths = list(directory.glob("*.json"))
    if not paths:
        raise CaseError(f"no case files in {directory}")
    return sorted((load_case(p) for p in paths), key=lambda c: c.name)


def rebuild_bundle(case: Case) -> dict:
    """Re-assemble the evidence bundle the model receives from the stored
    columns. The stored traceroute is already the merged/enriched form, so its
    hops, geo flag and notes are passed back through unchanged. Warm timing and
    run options are not stored, so they are absent (accepted fidelity limit)."""
    traceroute = case.evidence.get("traceroute") or {}
    return assemble_bundle(
        url=case.url,
        dns=case.evidence.get("dns"),
        samples=case.evidence.get("samples"),
        warm=None,
        traceroute=traceroute,
        enrichment={
            "hops": traceroute.get("hops", []),
            "geo_available": traceroute.get("geo_available", False),
            "notes": traceroute.get("enrichment_notes", []),
        },
        vantage=case.source.get("vantage"),
        request_options={},
    )
