"""Evidence validator (spec §2 guardrails, §5.2).

Every interpretive claim from the model carries an evidence citation. This
module checks — deterministically and **by existence only** — that each cited
string actually appears in the captured samples/DNS/traceroute. It verifies that
the evidence exists, never what it means, so it introduces no fixed signatures:
there are no header names or provider names anywhere in this file (a test
enforces that). A claim whose citation fails is downgraded to ``UNKNOWN`` and
recorded in a validation report attached to the verdict.

Matching rule (documented, tolerant to avoid false negatives — models cite
evidence descriptively, e.g. ``hop 2 org: <captured org>`` or
``CNAME <name> -> <target>``):
1. ``Name: value`` — a captured header with that name (case-insensitive) whose
   value CONTAINS the cited value (case-insensitive substring).
2. The text after a colon (>= 4 chars) is a substring of the captured corpus —
   covers ``<descriptive prefix>: <captured value>``.
3. ``Name`` alone — a captured header with that name exists.
4. ``AS<n>`` token — ``<n>`` matches a captured hop's autonomous-system number
   (normalizes the ``AS`` prefix onto the integer stored by enrichment).
5. The cited text is a substring of the captured corpus.
6. The cited text CONTAINS a captured value (>= 4 chars) — covers a verbose
   citation wrapping a real hostname/org/IP.

Fabricated values still fail: neither their value nor any captured token matches.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass

from app.llm.schema import StructuredResult

_REASON = "citation not found in captured evidence"
_NO_EVIDENCE = "no evidence provided for this claim"
_AS_TOKEN = re.compile(r"\bas(\d+)\b", re.IGNORECASE)


@dataclass
class ValidationFlag:
    path: str  # e.g. cache_verdict.layers[1].state
    citation: str
    reason: str


@dataclass
class ValidationResult:
    verdict: StructuredResult  # a copy with failed claims downgraded to UNKNOWN
    flags: list[ValidationFlag]

    @property
    def ok(self) -> bool:
        return not self.flags

    def report(self) -> dict:
        return {"ok": self.ok, "flags": [asdict(f) for f in self.flags]}

    def verdict_json(self) -> dict:
        """The validated cache_verdict + the validation report (stored in the
        verdict_json column, spec §6)."""
        data = self.verdict.cache_verdict.model_dump()
        data["validation"] = self.report()
        return data


class _EvidenceIndex:
    """A searchable view of the captured evidence for existence checks."""

    _MIN_TOKEN = 4  # ignore trivially-short captured values (e.g. Age "0")

    def __init__(self, bundle: dict) -> None:
        self._by_name: dict[str, list[str]] = defaultdict(list)
        self._numbers: set[int] = set()
        blob_parts: list[str] = []
        # Captured *values* (not header names) used for reverse-contains matching.
        values: list[str] = []

        for sample in bundle.get("samples") or []:
            for pair in sample.get("headers") or []:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    name, value = pair
                    self._by_name[str(name).strip().lower()].append(str(value))
                    blob_parts += [str(name), str(value), f"{name}: {value}"]
                    values.append(str(value))

        dns = bundle.get("dns") or {}
        if isinstance(dns, dict):
            for record in (dns.get("a") or []) + (dns.get("aaaa") or []) + (dns.get("ns") or []):
                blob_parts.append(str(record))
                values.append(str(record))
            for entry in dns.get("cname_chain") or []:
                if isinstance(entry, dict):
                    parts = [str(entry.get("name", "")), str(entry.get("cname", ""))]
                    blob_parts += parts
                    values += parts
            if dns.get("ttl") is not None:
                blob_parts.append(str(dns["ttl"]))

        traceroute = bundle.get("traceroute") or {}
        for hop in traceroute.get("hops") or []:
            if not isinstance(hop, dict):
                continue
            for key in ("ip", "rdns", "org", "city", "hint"):
                value = hop.get(key)
                if value:
                    blob_parts.append(str(value))
                    values.append(str(value))
            number = hop.get("asn")
            if isinstance(number, bool):
                continue
            if isinstance(number, int):
                self._numbers.add(number)
                blob_parts += [str(number), f"AS{number}"]
            elif isinstance(number, str) and number.strip().isdigit():
                self._numbers.add(int(number))
                blob_parts.append(number)

        self._blob = "\n".join(p for p in blob_parts if p).lower()
        self._tokens = {v.lower() for v in values if len(v) >= self._MIN_TOKEN}

    def contains(self, citation: str) -> bool:
        text = (citation or "").strip()
        if not text:
            return False
        lowered = text.lower()

        # 1/2. Name: value  (+ value-only fallback for "<prefix>: <captured value>")
        if ":" in text:
            name, _, value = text.partition(":")
            name = name.strip().lower()
            value = value.strip().lower()
            for captured in self._by_name.get(name, []):
                if value in captured.lower():
                    return True
            if len(value) >= self._MIN_TOKEN and value in self._blob:
                return True

        # 3. bare header name
        if lowered in self._by_name:
            return True

        # 4. AS<n> token
        match = _AS_TOKEN.search(text)
        if match and int(match.group(1)) in self._numbers:
            return True

        # 5. citation is a substring of the corpus
        if lowered in self._blob:
            return True

        # 6. citation wraps a captured value
        return any(token in lowered for token in self._tokens)


def validate_verdict(result: StructuredResult, bundle: dict) -> ValidationResult:
    """Validate every citation in ``result`` against ``bundle``; return a copy
    with failed claims downgraded to UNKNOWN plus a flag list."""
    index = _EvidenceIndex(bundle)
    verdict = result.model_copy(deep=True)
    flags: list[ValidationFlag] = []
    cv = verdict.cache_verdict
    downgraded_layers: set[str] = set()

    # Layers: any failed (or missing) citation downgrades the layer's state.
    for i, layer in enumerate(cv.layers):
        failed = [c for c in layer.evidence_headers if not index.contains(c)]
        if failed or not layer.evidence_headers:
            layer.state = "UNKNOWN"
            downgraded_layers.add(layer.layer_name)
            if not layer.evidence_headers:
                flags.append(ValidationFlag(f"cache_verdict.layers[{i}].state", "", _NO_EVIDENCE))
            for citation in failed:
                flags.append(ValidationFlag(f"cache_verdict.layers[{i}].state", citation, _REASON))

    # Per-sample states.
    for i, sample in enumerate(cv.sample_states):
        failed = [c for c in sample.evidence_headers if not index.contains(c)]
        if failed or not sample.evidence_headers:
            sample.state = "UNKNOWN"
            if not sample.evidence_headers:
                flags.append(ValidationFlag(f"cache_verdict.sample_states[{i}].state", "", _NO_EVIDENCE))
            for citation in failed:
                flags.append(ValidationFlag(f"cache_verdict.sample_states[{i}].state", citation, _REASON))

    # Provider identity.
    provider_failed = [c for c in cv.provider_evidence if not index.contains(c)]
    if provider_failed or not cv.provider_evidence:
        cv.provider = "UNKNOWN"
        if not cv.provider_evidence:
            flags.append(ValidationFlag("cache_verdict.provider", "", _NO_EVIDENCE))
        for citation in provider_failed:
            flags.append(ValidationFlag("cache_verdict.provider", citation, _REASON))

    # Serving-layer cascade: if the serving layer's own evidence failed, the
    # headline verdict is uncertain — lower confidence and flag it. The name is
    # kept as the best-effort boundary rather than blanked.
    if cv.serving_layer and cv.serving_layer in downgraded_layers:
        cv.confidence = "low"
        flags.append(ValidationFlag(
            "cache_verdict.serving_layer", cv.serving_layer,
            "serving-layer evidence failed validation; confidence lowered to low",
        ))

    # Findings: a finding often cites the ABSENCE of a header (e.g. a missing
    # security header) — its bare header name is legitimately not present, so it
    # is NOT flagged. Only a concrete "Name: value" claim asserts a captured
    # value, and that is checked for existence; a failure flags the finding
    # (kept, rendered with an 'unverified' tag; §8.3), never removed.
    for section, findings in (
        ("security_findings", verdict.security_findings),
        ("performance_findings", verdict.performance_findings),
    ):
        for i, finding in enumerate(findings):
            header = finding.evidence_header
            if ":" in header and not index.contains(header):
                flags.append(ValidationFlag(f"{section}[{i}].evidence_header", header, _REASON))

    return ValidationResult(verdict=verdict, flags=flags)
