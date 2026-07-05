"""OpenAICompatibleProvider: retry discipline per ADR-0003 (3 attempts, network/5xx only)."""

from __future__ import annotations

import httpx
import pytest

from flinq.core.config import Settings
from flinq.modules.ai_translation import provider as provider_mod
from flinq.modules.ai_translation.provider import (
    OpenAICompatibleProvider,
    ProviderRejected,
    ProviderUnavailable,
)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "llm_enabled": True,
        "llm_base_url": "https://llm.test/v1",
        "llm_api_key": "sk-test",
        "llm_model": "test-model",
        "llm_timeout_seconds": 5,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "позже\nпотом"}}],  # noqa: RUF001
            "usage": {"prompt_tokens": 42, "completion_tokens": 7},
        },
    )


@pytest.fixture(autouse=True)
def _no_backoff(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_mod, "_BACKOFF_BASE_SECONDS", 0.0)


async def test_success_parses_text_and_usage() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok_response()

    p = OpenAICompatibleProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    completion = await p.complete(system="s", user="u")
    assert completion.text == "позже\nпотом"  # noqa: RUF001
    assert completion.input_tokens == 42 and completion.output_tokens == 7
    [request] = seen
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"


async def test_no_auth_header_when_key_empty() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok_response()

    p = OpenAICompatibleProvider(
        _settings(llm_api_key=""), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    await p.complete(system="s", user="u")
    assert "authorization" not in seen[0].headers


async def test_retries_5xx_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500, text="boom")
        return _ok_response()

    p = OpenAICompatibleProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    completion = await p.complete(system="s", user="u")
    assert completion.text and calls["n"] == 3


async def test_persistent_5xx_raises_after_exactly_three_attempts() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="down")

    p = OpenAICompatibleProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ProviderUnavailable):
        await p.complete(system="s", user="u")
    assert calls["n"] == 3


async def test_transport_error_retried_then_raises() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("timeout")

    p = OpenAICompatibleProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ProviderUnavailable):
        await p.complete(system="s", user="u")
    assert calls["n"] == 3


async def test_4xx_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    p = OpenAICompatibleProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ProviderRejected):
        await p.complete(system="s", user="u")
    assert calls["n"] == 1


async def test_malformed_body_raises_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    p = OpenAICompatibleProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ProviderRejected):
        await p.complete(system="s", user="u")
