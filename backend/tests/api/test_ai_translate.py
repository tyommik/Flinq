"""POST /api/ai/translate — contract per spec (401/422/503/502/200)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.config import get_settings
from flinq.main import create_app
from flinq.modules.ai_translation import service
from flinq.modules.ai_translation.provider import (
    LLMCompletion,
    ProviderRejected,
    ProviderUnavailable,
)

BODY = {"surface_text": "later", "context_text": "See you later!", "target_language_code": "ru"}


async def _register_and_onboard(c: AsyncClient, email: str, lang: str = "en") -> str:
    r = await c.post(
        "/auth/register",
        json={"display_name": "T", "email": email, "password": "abcdefghij"},
    )
    assert r.status_code == 201
    csrf = c.cookies.get("flinq_csrf")
    assert csrf
    await c.post(
        "/me/onboarding",
        json={"ui_language": "en", "learning_languages": [lang], "translation_language": "ru"},
        headers={"X-CSRF-Token": csrf},
    )
    return csrf


class _GoodProvider:
    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        return LLMCompletion(text="позже\nпотом", input_tokens=1, output_tokens=1)  # noqa: RUF001


class _DownProvider:
    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        raise ProviderUnavailable("down")


class _RejectedProvider:
    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        raise ProviderRejected("bad key")


class _EmptyProvider:
    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        return LLMCompletion(text="\n \n", input_tokens=1, output_tokens=1)


@pytest.fixture(autouse=True)
def _llm_enabled(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", True)


@pytest.fixture(autouse=True)
async def _clean_audit(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    yield

    from sqlalchemy import delete

    from flinq.modules.ai_translation.models import AIRequest

    await db_session.execute(delete(AIRequest))
    await db_session.commit()


async def test_translate_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_default_provider", lambda: _GoodProvider())
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "ai-ok@example.com")
        r = await c.post("/api/ai/translate", json=BODY, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        body = r.json()
        assert [h["text"] for h in body["hints"]] == ["позже", "потом"]
        assert body["model"] and isinstance(body["latency_ms"], int)


async def test_translate_requires_auth() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/ai/translate", json=BODY)
        assert r.status_code == 403  # CSRF blocks before auth check (see test_lessons.py)


async def test_translate_validation() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "ai-422@example.com")
        for bad in (
            {**BODY, "surface_text": "y" * 257},
            {**BODY, "context_text": "y" * 1001},
            {**BODY, "target_language_code": "xx"},
            {**BODY, "surface_text": ""},
        ):
            r = await c.post("/api/ai/translate", json=bad, headers={"X-CSRF-Token": csrf})
            assert r.status_code == 422


async def test_translate_kill_switch_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", False)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "ai-503@example.com")
        r = await c.post("/api/ai/translate", json=BODY, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 503
        assert r.json()["detail"] == "ai_disabled"


async def test_translate_provider_down_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_default_provider", lambda: _DownProvider())
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "ai-502@example.com")
        r = await c.post("/api/ai/translate", json=BODY, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 502
        assert r.json()["detail"] == "ai_provider_error"


async def test_translate_provider_rejected_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_default_provider", lambda: _RejectedProvider())
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "ai-rejected@example.com")
        r = await c.post("/api/ai/translate", json=BODY, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 502
        assert r.json()["detail"] == "ai_provider_error"


async def test_translate_empty_response_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_default_provider", lambda: _EmptyProvider())
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "ai-empty@example.com")
        r = await c.post("/api/ai/translate", json=BODY, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 502
        assert r.json()["detail"] == "ai_empty_response"
