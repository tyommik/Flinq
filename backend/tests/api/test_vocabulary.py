import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from flinq.core.db import session_scope
from flinq.main import create_app
from flinq.modules.vocabulary.models import ItemTag, PersonalNote, PersonalTranslation, TokenItem


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    async with session_scope() as s:
        for model in (PersonalTranslation, PersonalNote, ItemTag, TokenItem):
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


async def test_lookup_new_word():
    async with await _client() as c:
        await _register(c)
        r = await c.get(
            "/api/vocabulary/lookup", params={"lang": "pt", "text": "Cada", "target": "ru"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "new" and body["item_id"] is None


async def test_create_then_translate_then_lookup():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        r = await c.post(
            "/api/vocabulary/items",
            headers=h,
            json={
                "kind": "token",
                "language_code": "pt",
                "text": "cada",
                "status": "tracked",
                "confidence": 0,
            },
        )
        assert r.status_code == 201
        item_id = r.json()["item_id"]
        r = await c.post(
            f"/api/vocabulary/items/token/{item_id}/translations",
            headers=h,
            json={
                "target_language_code": "ru",
                "translation_text": "каждый",
                "source_type": "user",
            },
        )
        assert r.status_code == 201
        r = await c.get(
            "/api/vocabulary/lookup", params={"lang": "pt", "text": "cada", "target": "ru"}
        )
        body = r.json()
        assert body["status"] == "tracked" and body["confidence"] == 0
        assert body["translations"]["primary"]["text"] == "каждый"


async def test_patch_tags_notes():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        item_id = (
            await c.post(
                "/api/vocabulary/items",
                headers=h,
                json={
                    "kind": "token",
                    "language_code": "pt",
                    "text": "cada",
                    "status": "tracked",
                    "confidence": 0,
                },
            )
        ).json()["item_id"]
        r = await c.patch(
            f"/api/vocabulary/items/token/{item_id}",
            headers=h,
            json={"status": "known", "confidence": None},
        )
        assert r.status_code == 200 and r.json()["status"] == "known"
        r = await c.post(
            f"/api/vocabulary/items/token/{item_id}/tags", headers=h, json={"tag_name": "verbs"}
        )
        assert r.status_code == 200 and r.json()["tags"] == ["verbs"]
        r = await c.put(
            f"/api/vocabulary/items/token/{item_id}/notes", headers=h, json={"note_text": "hello"}
        )
        assert r.status_code == 200 and r.json()["note"] == "hello"


async def test_lookup_requires_auth():
    async with await _client() as c:
        r = await c.get(
            "/api/vocabulary/lookup", params={"lang": "pt", "text": "x", "target": "ru"}
        )
        assert r.status_code == 401


async def _item_with_translation(c: AsyncClient, h: dict[str, str]) -> tuple[str, str]:
    r = await c.post(
        "/api/vocabulary/items",
        headers=h,
        json={
            "kind": "token",
            "language_code": "pt",
            "text": "cada",
            "status": "tracked",
            "confidence": 0,
        },
    )
    assert r.status_code == 201
    item_id = r.json()["item_id"]
    r = await c.post(
        f"/api/vocabulary/items/token/{item_id}/translations",
        headers=h,
        json={"target_language_code": "ru", "translation_text": "первый", "source_type": "user"},
    )
    assert r.status_code == 201
    return item_id, r.json()["id"]


async def test_post_duplicate_translation_returns_200_with_existing_row():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        item_id, tr_id = await _item_with_translation(c, h)
        r = await c.post(
            f"/api/vocabulary/items/token/{item_id}/translations",
            headers=h,
            json={
                "target_language_code": "ru",
                "translation_text": "первый",
                "source_type": "dictionary",
            },
        )
        assert r.status_code == 200
        assert r.json()["id"] == tr_id


async def test_patch_translation_text_and_409_on_duplicate():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        item_id, tr_id = await _item_with_translation(c, h)
        r = await c.patch(
            f"/api/vocabulary/items/token/{item_id}/translations/{tr_id}",
            headers=h,
            json={"translation_text": "поправленный"},
        )
        assert r.status_code == 200
        assert r.json()["text"] == "поправленный" and r.json()["source_type"] == "user"
        r = await c.post(
            f"/api/vocabulary/items/token/{item_id}/translations",
            headers=h,
            json={
                "target_language_code": "ru",
                "translation_text": "второй",
                "source_type": "user",
            },
        )
        second_id = r.json()["id"]
        r = await c.patch(
            f"/api/vocabulary/items/token/{item_id}/translations/{second_id}",
            headers=h,
            json={"translation_text": "поправленный"},
        )
        assert r.status_code == 409


async def test_delete_translation_promotes_and_returns_list():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        item_id, first_id = await _item_with_translation(c, h)
        r = await c.post(
            f"/api/vocabulary/items/token/{item_id}/translations",
            headers=h,
            json={
                "target_language_code": "ru",
                "translation_text": "второй",
                "source_type": "user",
            },
        )
        assert r.status_code == 201
        r = await c.delete(
            f"/api/vocabulary/items/token/{item_id}/translations/{first_id}", headers=h
        )
        assert r.status_code == 200
        body = r.json()
        assert [t["text"] for t in body["translations"]] == ["второй"]
        assert body["translations"][0]["is_primary"] is True


async def test_translation_routes_404_on_foreign_translation():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        item_id, _ = await _item_with_translation(c, h)
        missing = uuid.uuid4()
        r = await c.patch(
            f"/api/vocabulary/items/token/{item_id}/translations/{missing}",
            headers=h,
            json={"translation_text": "х"},  # noqa: RUF001 -- Cyrillic literal, intentional
        )
        assert r.status_code == 404
        r = await c.delete(
            f"/api/vocabulary/items/token/{item_id}/translations/{missing}", headers=h
        )
        assert r.status_code == 404
