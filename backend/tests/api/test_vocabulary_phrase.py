"""API: карточка фразы end-to-end (create/lookup/patch/translations)."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from flinq.core.db import session_scope
from flinq.main import create_app
from flinq.modules.vocabulary.models import (
    ItemTag,
    PersonalNote,
    PersonalTranslation,
    PhraseItem,
    TokenItem,
)


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    async with session_scope() as s:
        for model in (PersonalTranslation, PersonalNote, ItemTag, PhraseItem, TokenItem):
            await s.execute(delete(model))


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def _register(c: AsyncClient) -> str:
    r = await c.post(
        "/auth/register",
        json={
            "display_name": "T",
            "email": f"{uuid.uuid4().hex}@t.io",
            "password": "abcdefghij",
        },
    )
    assert r.status_code == 201
    csrf = c.cookies.get("flinq_csrf")
    assert csrf
    return csrf


async def test_lookup_unknown_phrase_returns_new():
    async with await _client() as c:
        await _register(c)
        r = await c.get(
            "/api/vocabulary/lookup",
            params={"lang": "en", "text": "so far, so good", "target": "ru", "kind": "phrase"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["item_id"] is None and body["status"] == "new"


async def test_create_phrase_then_lookup_normalizes():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        r = await c.post(
            "/api/vocabulary/items",
            headers=h,
            json={
                "kind": "phrase", "language_code": "en",
                "text": "So Far, so GOOD", "status": "tracked", "confidence": 1,
            },
        )
        assert r.status_code == 201, r.text
        item_id = r.json()["item_id"]
        # lookup по другому поверхностному варианту той же фразы
        r = await c.get(
            "/api/vocabulary/lookup",
            params={"lang": "en", "text": "so far so good", "target": "ru", "kind": "phrase"},
        )
        assert r.json()["item_id"] == item_id
        assert r.json()["status"] == "tracked"


async def test_create_phrase_is_upsert():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        body: dict[str, Any] = {
            "kind": "phrase", "language_code": "en",
            "text": "give up", "status": "tracked", "confidence": 1,
        }
        r1 = await c.post("/api/vocabulary/items", headers=h, json=body)
        body["status"], body["confidence"] = "known", None
        r2 = await c.post("/api/vocabulary/items", headers=h, json=body)
        assert r1.json()["item_id"] == r2.json()["item_id"]
        assert r2.json()["status"] == "known"


async def test_create_phrase_rejects_one_and_nine_words():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        for text in ("alone", "a b c d e f g h i"):
            r = await c.post(
                "/api/vocabulary/items",
                headers=h,
                json={
                    "kind": "phrase", "language_code": "en",
                    "text": text, "status": "tracked", "confidence": 1,
                },
            )
            assert r.status_code == 422, text


async def test_phrase_translations_and_patch():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        r = await c.post(
            "/api/vocabulary/items",
            headers=h,
            json={
                "kind": "phrase", "language_code": "en",
                "text": "give up", "status": "tracked", "confidence": 1,
            },
        )
        item_id = r.json()["item_id"]
        r = await c.post(
            f"/api/vocabulary/items/phrase/{item_id}/translations",
            headers=h,
            json={"target_language_code": "ru", "translation_text": "сдаться"},
        )
        assert r.status_code == 201 and r.json()["is_primary"] is True
        r = await c.patch(
            f"/api/vocabulary/items/phrase/{item_id}",
            headers=h,
            json={"status": "tracked", "confidence": 3},
        )
        assert r.status_code == 200 and r.json()["confidence"] == 3
