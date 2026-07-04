"""The analysis call (spec §5.2, §5.3): bundle -> StructuredResult.

Builds the user message from the evidence bundle, calls the provider, and parses
its raw text strictly (no code-fence stripping — a fenced/prose response is
rejected and retried once, per §5.2 "strict JSON only"). Two failures raise
``AnalysisParseError``, which the degraded path (T14) consumes so evidence is
never lost.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.llm.base import DEFAULT_SETTINGS, LLMProvider, LLMSettings
from app.llm.prompt import SYSTEM_PROMPT
from app.llm.schema import StructuredResult

_RETRY_CORRECTION = (
    "Your previous response was not valid JSON matching the schema. "
    "Return ONLY the JSON object — no prose, no markdown code fences."
)


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


async def run_analysis(
    bundle: dict,
    *,
    provider: LLMProvider,
    model: str,
    settings: LLMSettings = DEFAULT_SETTINGS,
    max_retries: int = 1,
) -> StructuredResult:
    """One structured analysis call with ``max_retries`` retries on invalid JSON.

    Returns a validated StructuredResult or raises AnalysisParseError.
    """
    base_user = build_user_message(bundle)
    attempts = max_retries + 1
    last_raw: str | None = None
    last_error: Exception | None = None

    for attempt in range(attempts):
        user = base_user if attempt == 0 else f"{_RETRY_CORRECTION}\n\n{base_user}"
        last_raw = await provider.analyze(
            system=SYSTEM_PROMPT, user=user, model=model, settings=settings
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
