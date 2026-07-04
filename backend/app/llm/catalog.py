"""Available-models catalog for GET /api/models (spec §7, §5.1).

A provider is "available" only when its API key env var is set. This module
returns model **ids** and display names — never key material (spec §10). T11
replaces the static lists with each provider's live ``list_models()`` while
keeping this ``available_models()`` contract.
"""

from __future__ import annotations

import os

# provider id -> (display name, env var, [(model id, display name)])
_CATALOG: dict[str, dict] = {
    "anthropic": {
        "name": "Anthropic",
        "env": "ANTHROPIC_API_KEY",
        "models": [
            {"id": "claude-opus-4-8", "name": "Claude Opus 4.8"},
            {"id": "claude-sonnet-5", "name": "Claude Sonnet 5"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
        ],
    },
    "openrouter": {
        "name": "OpenRouter",
        "env": "OPENROUTER_API_KEY",
        "models": [
            {"id": "anthropic/claude-opus-4-8", "name": "Claude Opus 4.8"},
            {"id": "anthropic/claude-sonnet-5", "name": "Claude Sonnet 5"},
            {"id": "openai/gpt-5", "name": "GPT-5"},
        ],
    },
}


def available_models() -> dict:
    """{"providers": [{"id", "name", "models": [{"id", "name"}]}]} for every
    provider whose API key is configured. Empty when none are set."""
    providers = []
    for provider_id, config in _CATALOG.items():
        if os.getenv(config["env"]):
            providers.append(
                {"id": provider_id, "name": config["name"], "models": config["models"]}
            )
    return {"providers": providers}
