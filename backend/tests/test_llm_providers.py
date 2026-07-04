"""T11 — LLM provider abstraction (spec §5.1).

Scenarios:
  1. Mocked Anthropic/OpenRouter -> normalized text; request bodies carry the
     right model id + deterministic settings.
  2. No ANTHROPIC_API_KEY -> absent from registry + /api/models; configured stays.
  3. 429/500 -> retryable ProviderError; auth (401) distinct + non-retryable.
  4. Keys never appear in exceptions/logs.
  5. @live smoke per provider (skipped without a key).

Note on temperature: current Anthropic models reject `temperature` (400), so the
Anthropic body omits it and OpenRouter (OpenAI-compatible) carries temperature 0
— see the module/decision notes. Scenario 1 asserts this reality.
"""

import json
import logging

import httpx
import pytest
import respx

from app.llm.anthropic import AnthropicProvider
from app.llm.base import ProviderError
from app.llm.openrouter import OpenRouterProvider
from app.llm.registry import available_models, build_registry, get_provider

ANTHROPIC_MSGS = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODELS = "https://api.anthropic.com/v1/models"
OPENROUTER_CHAT = "https://openrouter.ai/api/v1/chat/completions"


# --- Scenario 1 ---------------------------------------------------------------

@respx.mock
async def test_anthropic_analyze_returns_text_and_body():
    route = respx.post(ANTHROPIC_MSGS).mock(
        return_value=httpx.Response(200, json={"content": [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": '{"cached": true}'},
        ]})
    )
    provider = AnthropicProvider("sk-ant-test-key")
    text = await provider.analyze(system="SYS", user="USR", model="claude-opus-4-8")

    assert text == '{"cached": true}'
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "claude-opus-4-8"
    assert body["system"] == "SYS"
    assert body["messages"] == [{"role": "user", "content": "USR"}]
    # Current Anthropic models reject temperature -> intentionally absent.
    assert "temperature" not in body
    assert route.calls.last.request.headers["x-api-key"] == "sk-ant-test-key"


@respx.mock
async def test_openrouter_analyze_returns_text_and_body():
    route = respx.post(OPENROUTER_CHAT).mock(
        return_value=httpx.Response(200, json={"choices": [
            {"message": {"content": "OR RESPONSE"}},
        ]})
    )
    provider = OpenRouterProvider("sk-or-test-key")
    text = await provider.analyze(system="s", user="u", model="anthropic/claude-opus-4-8")

    assert text == "OR RESPONSE"
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "anthropic/claude-opus-4-8"
    assert body["temperature"] == 0  # OpenAI-compatible: temperature honored
    assert body["messages"][0] == {"role": "system", "content": "s"}
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-or-test-key"


@respx.mock
async def test_list_models_maps_and_falls_back():
    respx.get(ANTHROPIC_MODELS).mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "claude-opus-4-8", "display_name": "Claude Opus 4.8"},
        ]})
    )
    models = await AnthropicProvider("k").list_models()
    assert {"id": "claude-opus-4-8", "name": "Claude Opus 4.8"} in models

    # On error, falls back to the static list (used by /api/models robustness).
    with respx.mock:
        respx.get(ANTHROPIC_MODELS).mock(return_value=httpx.Response(500))
        fallback = await AnthropicProvider("k").list_models()
    assert fallback == AnthropicProvider("k").static_models()


# --- Scenario 2 ---------------------------------------------------------------

def test_registry_only_exposes_configured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-xyz")

    registry = build_registry()
    assert set(registry) == {"openrouter"}
    assert get_provider("anthropic") is None
    assert get_provider("openrouter") is not None

    providers = available_models()["providers"]
    assert [p["id"] for p in providers] == ["openrouter"]
    assert providers[0]["models"]  # non-empty


def test_registry_both_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENROUTER_API_KEY", "b")
    assert set(build_registry()) == {"anthropic", "openrouter"}
    # Order is anthropic first (registry factory order).
    assert [p["id"] for p in available_models()["providers"]] == ["anthropic", "openrouter"]


# --- Scenario 3 ---------------------------------------------------------------

@respx.mock
async def test_auth_error_is_non_retryable():
    respx.post(ANTHROPIC_MSGS).mock(
        return_value=httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})
    )
    with pytest.raises(ProviderError) as exc_info:
        await AnthropicProvider("sk-bad").analyze(system="s", user="u", model="m")
    assert exc_info.value.retryable is False
    assert exc_info.value.kind == "auth"
    assert exc_info.value.status_code == 401


@respx.mock
async def test_rate_limit_is_retryable():
    respx.post(ANTHROPIC_MSGS).mock(return_value=httpx.Response(429, text="slow down"))
    with pytest.raises(ProviderError) as exc_info:
        await AnthropicProvider("k").analyze(system="s", user="u", model="m")
    assert exc_info.value.retryable is True
    assert exc_info.value.kind == "rate_limit"


@respx.mock
async def test_server_error_is_retryable():
    respx.post(OPENROUTER_CHAT).mock(return_value=httpx.Response(503, text="overloaded"))
    with pytest.raises(ProviderError) as exc_info:
        await OpenRouterProvider("k").analyze(system="s", user="u", model="m")
    assert exc_info.value.retryable is True
    assert exc_info.value.kind == "transient"


@respx.mock
async def test_connection_error_is_retryable():
    respx.post(ANTHROPIC_MSGS).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ProviderError) as exc_info:
        await AnthropicProvider("k").analyze(system="s", user="u", model="m")
    assert exc_info.value.retryable is True
    assert exc_info.value.kind == "transient"


# --- Scenario 4 ---------------------------------------------------------------

@respx.mock
async def test_key_never_leaks_in_exception(caplog):
    secret = "sk-ant-SUPERSECRET-9999"
    respx.post(ANTHROPIC_MSGS).mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ProviderError) as exc_info:
            await AnthropicProvider(secret).analyze(system="s", user="u", model="m")

    assert secret not in str(exc_info.value)
    assert secret not in repr(exc_info.value)
    assert secret not in caplog.text


# --- Scenario 5 (live, excluded by default) ----------------------------------

@pytest.mark.live
async def test_anthropic_live_smoke():
    import os

    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    text = await AnthropicProvider(key).analyze(
        system="Reply with exactly the single word: OK",
        user="Go.",
        model="claude-haiku-4-5",
    )
    assert "OK" in text.upper()


@pytest.mark.live
async def test_openrouter_live_smoke():
    import os

    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        pytest.skip("OPENROUTER_API_KEY not set")
    text = await OpenRouterProvider(key).analyze(
        system="Reply with exactly the single word: OK",
        user="Go.",
        model="anthropic/claude-haiku-4-5",
    )
    assert "OK" in text.upper()
