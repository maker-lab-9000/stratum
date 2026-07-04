"""Provider registry (spec §5.1) — only exposes providers whose API key is set.

Adding a provider = append one `(env_var, class)` row. `available_models()` is
the GET /api/models contract (env-key driven, static lists, no live call —
offline and fast); live listing is each provider's `list_models()`.
"""

from __future__ import annotations

import os

from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.openrouter import OpenRouterProvider

# Order determines display order in /api/models.
_FACTORIES: list[tuple[str, type[LLMProvider]]] = [
    ("ANTHROPIC_API_KEY", AnthropicProvider),
    ("OPENROUTER_API_KEY", OpenRouterProvider),
]


def build_registry(env: dict | None = None) -> dict[str, LLMProvider]:
    """Instantiate every provider whose API key is present in the environment."""
    env = env if env is not None else os.environ
    registry: dict[str, LLMProvider] = {}
    for var, provider_cls in _FACTORIES:
        key = env.get(var)
        if key:
            provider = provider_cls(key)
            registry[provider.id] = provider
    return registry


def get_provider(name: str, env: dict | None = None) -> LLMProvider | None:
    return build_registry(env).get(name)


def available_models(env: dict | None = None) -> dict:
    """{"providers": [{"id", "name", "models": [{"id", "name"}]}]} for every
    configured provider. Static model lists — never returns key material (§10)."""
    registry = build_registry(env)
    return {
        "providers": [
            {"id": p.id, "name": p.name, "models": p.static_models()}
            for p in registry.values()
        ]
    }
