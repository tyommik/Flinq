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


async def _create_item(c: AsyncClient, h: dict[str, str], text: str) -> str:
    r = await c.post(
        "/api/vocabulary/items",
        headers=h,
        json={
            "kind": "token",
            "language_code": "pt",
            "text": text,
            "status": "tracked",
            "confidence": 1,
        },
    )
    assert r.status_code == 201
    return r.json()["item_id"]


async def test_list_returns_items_with_defaults():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        await _create_item(c, h, "cada")
        await _create_item(c, h, "porta")
        r = await c.get("/api/vocabulary", params={"lang": "pt"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2 and body["page"] == 1 and body["page_size"] == 25
        # created_at desc default: porta created last comes first
        assert [i["text"] for i in body["items"]] == ["porta", "cada"]
        assert body["items"][0]["primary_translation"] is None


async def test_list_filters_and_search_params():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        await _create_item(c, h, "cada")
        r = await c.get(
            "/api/vocabulary",
            params={"lang": "pt", "status": ["known"], "q": "cada"},
        )
        assert r.status_code == 200 and r.json()["total"] == 0
        r = await c.get(
            "/api/vocabulary",
            params={"lang": "pt", "status": ["tracked"], "q": "cad"},
        )
        assert r.json()["total"] == 1


async def test_list_accepts_explicit_page_size():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        await _create_item(c, h, "cada")
        r = await c.get(
            "/api/vocabulary",
            params={"lang": "pt", "page_size": 50},
        )
        assert r.status_code == 200
        assert r.json()["page_size"] == 50


async def test_list_rejects_invalid_page_size():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        await _create_item(c, h, "cada")
        r = await c.get(
            "/api/vocabulary",
            params={"lang": "pt", "page_size": 30},
        )
        assert r.status_code == 422


async def test_list_requires_auth():
    async with await _client() as c:
        r = await c.get("/api/vocabulary", params={"lang": "pt"})
        assert r.status_code == 401


async def test_bulk_set_known_and_delete():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        a = await _create_item(c, h, "cada")
        b = await _create_item(c, h, "porta")
        r = await c.post(
            "/api/vocabulary/bulk",
            headers=h,
            json={"item_ids": [a, b], "action": "set_known"},
        )
        assert r.status_code == 200 and r.json()["affected"] == 2
        r = await c.post(
            "/api/vocabulary/bulk",
            headers=h,
            json={"item_ids": [a], "action": "delete"},
        )
        assert r.status_code == 200 and r.json()["affected"] == 1
        r = await c.get("/api/vocabulary", params={"lang": "pt"})
        assert r.json()["total"] == 1


async def test_bulk_validation_422():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        r = await c.post(
            "/api/vocabulary/bulk",
            headers=h,
            json={"item_ids": [str(uuid.uuid4())] * 501, "action": "set_known"},
        )
        assert r.status_code == 422
        r = await c.post(
            "/api/vocabulary/bulk",
            headers=h,
            json={"item_ids": [str(uuid.uuid4())], "action": "add_tag"},
        )
        assert r.status_code == 422


async def test_list_added_by_param():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        await _create_item(c, h, "cada")  # explicit create → added_by user
        r = await c.get("/api/vocabulary", params={"lang": "pt", "added_by": "all"})
        assert r.status_code == 200 and r.json()["total"] == 1
        r = await c.get("/api/vocabulary", params={"lang": "pt", "added_by": "bogus"})
        assert r.status_code == 422
