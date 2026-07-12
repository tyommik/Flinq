"""list_items: union токенов и фраз (kind=token|phrase|all)."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo
from flinq.modules.vocabulary import service
from flinq.modules.vocabulary.models import (
    ItemTag,
    PersonalNote,
    PersonalTranslation,
    PhraseItem,
    TokenItem,
)

LIST_DEFAULTS: dict[str, Any] = {
    "target_language_code": "ru",
    "statuses": ["tracked", "known", "ignored"],
    "confidence_min": None,
    "confidence_max": None,
    "tags": [],
    "q": None,
    "added_after": None,
    "sort": "created_at",
    "sort_dir": "desc",
    "page": 1,
    "page_size": 25,
    "added_by": "user",
}


async def _make_user(s: AsyncSession) -> uuid.UUID:
    user = await UserRepo(s).create(
        email=f"{uuid.uuid4().hex}@t.io",
        password_hash=hash_password("x"),
        display_name="T",
        role="learner",
    )
    await s.flush()
    return user.id


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    async with session_scope() as s:
        for model in (PersonalTranslation, PersonalNote, ItemTag, PhraseItem, TokenItem):
            await s.execute(delete(model))


async def _seed(user_id: uuid.UUID) -> None:
    async with session_scope() as s:
        s.add(TokenItem(
            user_id=user_id, language_code="en", token_text="far",
            status="tracked", confidence=1,
        ))
        s.add(PhraseItem(
            user_id=user_id, language_code="en",
            phrase_text="so far so good", display_text="so far, so good",
            status="tracked", confidence=2,
        ))


async def test_kind_all_returns_both():
    async with session_scope() as s:
        user_id = await _make_user(s)
    await _seed(user_id)
    async with session_scope() as s:
        items, total = await service.list_items(
            s, user_id=user_id, language_code="en", kind="all", **LIST_DEFAULTS
        )
        assert total == 2
        assert {(i.kind, i.text) for i in items} == {
            ("token", "far"), ("phrase", "so far, so good"),
        }
        phrase = next(i for i in items if i.kind == "phrase")
        assert phrase.pos is None and phrase.context is None


async def test_kind_filters():
    async with session_scope() as s:
        user_id = await _make_user(s)
    await _seed(user_id)
    async with session_scope() as s:
        items, total = await service.list_items(
            s, user_id=user_id, language_code="en", kind="phrase", **LIST_DEFAULTS
        )
        assert total == 1 and items[0].kind == "phrase"
        items, total = await service.list_items(
            s, user_id=user_id, language_code="en", kind="token", **LIST_DEFAULTS
        )
        assert total == 1 and items[0].kind == "token"


async def test_q_searches_phrase_display_text():
    async with session_scope() as s:
        user_id = await _make_user(s)
    await _seed(user_id)
    async with session_scope() as s:
        kw: dict[str, Any] = {**LIST_DEFAULTS, "q": "so good"}
        items, total = await service.list_items(
            s, user_id=user_id, language_code="en", kind="all", **kw,
        )
        assert total == 1 and items[0].kind == "phrase"


async def test_phrase_primary_translation_hydrated():
    async with session_scope() as s:
        user_id = await _make_user(s)
    await _seed(user_id)
    async with session_scope() as s:
        phrase_id = (await s.execute(select(PhraseItem.id))).scalar_one()
        await service.add_translation(
            s, user_id=user_id, kind="phrase", item_id=phrase_id,
            target_language_code="ru", translation_text="пока всё хорошо",
            source_type="user",
        )
    async with session_scope() as s:
        items, _ = await service.list_items(
            s, user_id=user_id, language_code="en", kind="phrase", **LIST_DEFAULTS
        )
        assert items[0].primary_translation_text == "пока всё хорошо"
