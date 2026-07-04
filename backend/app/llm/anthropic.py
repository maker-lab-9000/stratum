"""Anthropic provider (direct Messages API, spec §5.1)."""

from __future__ import annotations

from app.llm.base import (
    DEFAULT_SETTINGS,
    DEFAULT_TIMEOUT_S,
    LLMProvider,
    LLMSettings,
    request_json,
)

_API = "https://api.anthropic.com/v1"
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    name = "Anthropic"

    _STATIC = [
        {"id": "claude-opus-4-8", "name": "Claude Opus 4.8"},
        {"id": "claude-sonnet-5", "name": "Claude Sonnet 5"},
        {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5"},
    ]

    def __init__(self, api_key: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self._key = api_key
        self._timeout = timeout

    def _headers(self) -> dict:
        return {
            "x-api-key": self._key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def static_models(self) -> list[dict]:
        return [dict(m) for m in self._STATIC]

    async def list_models(self) -> list[dict]:
        try:
            data = await request_json(
                "GET", f"{_API}/models", headers=self._headers(),
                provider=self.id, timeout=self._timeout,
            )
            return [
                {"id": m["id"], "name": m.get("display_name", m["id"])}
                for m in data.get("data", [])
            ]
        except Exception:
            return self.static_models()

    async def analyze(
        self, *, system: str, user: str, model: str, settings: LLMSettings = DEFAULT_SETTINGS
    ) -> str:
        # `temperature` is intentionally omitted: current Anthropic models reject
        # it with a 400 (see base.py note). max_tokens is honored.
        body = {
            "model": model,
            "max_tokens": settings.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data = await request_json(
            "POST", f"{_API}/messages", headers=self._headers(),
            provider=self.id, timeout=self._timeout, json=body,
        )
        return _extract_text(data)


def _extract_text(data: dict) -> str:
    """Join the text of all `text` content blocks (skips empty thinking blocks)."""
    return "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    )
