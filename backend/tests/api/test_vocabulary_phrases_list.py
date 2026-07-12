"""GET /api/vocabulary/phrases — лёгкий список для клиентского матчинга."""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from flinq.core.db import session_scope
from flinq.main import create_app
from flinq.modules.vocabulary.models import PhraseItem


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    async with session_scope() as s:
        await s.execute(delete(PhraseItem))


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def _register(c: AsyncClient) -> str:
    email = f"{uuid.uuid4().hex}@t.io"
    r = await c.post(
        "/auth/register",
        json={"email": email, "password": "abcdefghij", "display_name": "T"},
    )
    assert r.status_code == 201, r.text
    csrf = c.cookies.get("flinq_csrf")
    assert csrf
    return csrf


async def _create_phrase(c: AsyncClient, csrf: str, text: str, lang: str = "en") -> str:
    r = await c.post(
        "/api/vocabulary/items",
        json={
            "kind": "phrase", "language_code": lang,
            "text": text, "status": "tracked", "confidence": 1,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 201, r.text
    return r.json()["item_id"]


async def test_lists_only_own_lang_phrases():
    async with await _client() as c:
        csrf = await _register(c)
        pid = await _create_phrase(c, csrf, "so far, so good")
        await _create_phrase(c, csrf, "тем не менее", lang="ru")
        r = await c.get("/api/vocabulary/phrases", params={"lang": "en"})
        assert r.status_code == 200
        phrases = r.json()["phrases"]
        assert [p["item_id"] for p in phrases] == [pid]
        assert phrases[0]["phrase_text"] == "so far so good"
        assert phrases[0]["status"] == "tracked"
        assert phrases[0]["confidence"] == 1


async def test_requires_auth():
    async with await _client() as c:
        r = await c.get("/api/vocabulary/phrases", params={"lang": "en"})
        assert r.status_code == 401


async def test_does_not_see_foreign_users_phrases():
    async with await _client() as c:
        csrf1 = await _register(c)
        await _create_phrase(c, csrf1, "give up")
        await _register(c)
        r = await c.get("/api/vocabulary/phrases", params={"lang": "en"})
        assert r.json()["phrases"] == []
