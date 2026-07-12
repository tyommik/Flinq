"""bulk_action покрывает phrase_items."""

import uuid
from collections.abc import AsyncIterator

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


async def _seed(user_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    async with session_scope() as s:
        token = TokenItem(
            user_id=user_id, language_code="en", token_text="far",
            status="tracked", confidence=1,
        )
        phrase = PhraseItem(
            user_id=user_id, language_code="en",
            phrase_text="so far so good", display_text="so far, so good",
            status="tracked", confidence=1,
        )
        s.add_all([token, phrase])
        await s.flush()
        return token.id, phrase.id


async def test_set_known_covers_both_kinds():
    async with session_scope() as s:
        user_id = await _make_user(s)
    token_id, phrase_id = await _seed(user_id)
    async with session_scope() as s:
        affected = await service.bulk_action(
            s, user_id=user_id, item_ids=[token_id, phrase_id],
            action="set_known", tag_name=None,
        )
        assert affected == 2
    async with session_scope() as s:
        phrase = await s.get(PhraseItem, phrase_id)
        assert phrase is not None and phrase.status == "known" and phrase.confidence is None


async def test_delete_phrase_removes_satellites():
    async with session_scope() as s:
        user_id = await _make_user(s)
    _, phrase_id = await _seed(user_id)
    async with session_scope() as s:
        await service.add_tag(s, user_id=user_id, kind="phrase", item_id=phrase_id, tag_name="x")
    async with session_scope() as s:
        affected = await service.bulk_action(
            s, user_id=user_id, item_ids=[phrase_id], action="delete", tag_name=None
        )
        assert affected == 1
    async with session_scope() as s:
        assert await s.get(PhraseItem, phrase_id) is None
        tags = (await s.execute(select(ItemTag))).scalars().all()
        assert tags == []


async def test_add_tag_covers_phrase():
    async with session_scope() as s:
        user_id = await _make_user(s)
    _, phrase_id = await _seed(user_id)
    async with session_scope() as s:
        affected = await service.bulk_action(
            s, user_id=user_id, item_ids=[phrase_id], action="add_tag", tag_name="idiom"
        )
        assert affected == 1
    async with session_scope() as s:
        tag = (await s.execute(select(ItemTag))).scalar_one()
        assert tag.item_kind == "phrase" and tag.tag_name == "idiom"
