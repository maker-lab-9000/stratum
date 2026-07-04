"""OpenRouter provider (OpenAI-compatible gateway, spec §5.1)."""

from __future__ import annotations

from app.llm.base import (
    DEFAULT_SETTINGS,
    DEFAULT_TIMEOUT_S,
    LLMProvider,
    LLMSettings,
    request_json,
)

_API = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    id = "openrouter"
    name = "OpenRouter"

    _STATIC = [
        {"id": "anthropic/claude-opus-4-8", "name": "Claude Opus 4.8"},
        {"id": "anthropic/claude-sonnet-5", "name": "Claude Sonnet 5"},
        {"id": "openai/gpt-5", "name": "GPT-5"},
    ]

    def __init__(self, api_key: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self._key = api_key
        self._timeout = timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._key}", "content-type": "application/json"}

    def static_models(self) -> list[dict]:
        return [dict(m) for m in self._STATIC]

    async def list_models(self) -> list[dict]:
        try:
            data = await request_json(
                "GET", f"{_API}/models", headers=self._headers(),
                provider=self.id, timeout=self._timeout,
            )
            return [
                {"id": m["id"], "name": m.get("name", m["id"])}
                for m in data.get("data", [])
            ]
        except Exception:
            return self.static_models()

    async def analyze(
        self, *, system: str, user: str, model: str, settings: LLMSettings = DEFAULT_SETTINGS
    ) -> str:
        # OpenAI-compatible: temperature IS accepted here (unlike the Anthropic
        # direct API), so send the centralized temperature for determinism.
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": settings.temperature,
            "max_tokens": settings.max_tokens,
        }
        data = await request_json(
            "POST", f"{_API}/chat/completions", headers=self._headers(),
            provider=self.id, timeout=self._timeout, json=body,
        )
        return data["choices"][0]["message"]["content"]
