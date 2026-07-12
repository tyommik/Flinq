"""Сателлиты (translations/notes/tags) для kind='phrase' (FLQ phrase selection)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
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


async def _phrase_item(user_id: uuid.UUID) -> uuid.UUID:
    async with session_scope() as s:
        item = PhraseItem(
            user_id=user_id,
            language_code="en",
            phrase_text="so far so good",
            display_text="so far, so good",
            status="tracked",
            confidence=1,
        )
        s.add(item)
        await s.flush()
        return item.id


async def test_phrase_translation_roundtrip():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _phrase_item(user_id)
    async with session_scope() as s:
        row, created = await service.add_translation(
            s, user_id=user_id, kind="phrase", item_id=item_id,
            target_language_code="ru", translation_text="пока всё хорошо",
            source_type="user",
        )
        assert created and row.is_primary and row.item_kind == "phrase"
    async with session_scope() as s:
        updated = await service.update_translation(
            s, user_id=user_id, kind="phrase", item_id=item_id,
            translation_id=row.id, translation_text="пока что неплохо",
        )
        assert updated.translation_text == "пока что неплохо"
    async with session_scope() as s:
        remaining = await service.delete_translation(
            s, user_id=user_id, kind="phrase", item_id=item_id, translation_id=row.id
        )
        assert remaining == []


async def test_phrase_note_and_tags():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _phrase_item(user_id)
    async with session_scope() as s:
        note = await service.put_note(
            s, user_id=user_id, kind="phrase", item_id=item_id, note_text="идиома"
        )
        assert note.item_kind == "phrase"
    async with session_scope() as s:
        tags = await service.add_tag(
            s, user_id=user_id, kind="phrase", item_id=item_id, tag_name="idiom"
        )
        assert tags == ["idiom"]
    async with session_scope() as s:
        tags = await service.remove_tag(
            s, user_id=user_id, kind="phrase", item_id=item_id, tag_name="idiom"
        )
        assert tags == []


async def test_satellites_do_not_leak_across_kinds():
    """Токен и фраза с одинаковым item_id-скоупом не видят чужие сателлиты."""  # noqa: RUF002
    async with session_scope() as s:
        user_id = await _make_user(s)
        token = TokenItem(
            user_id=user_id, language_code="en", token_text="far",
            status="tracked", confidence=1,
        )
        s.add(token)
        await s.flush()
        token_id = token.id
    item_id = await _phrase_item(user_id)
    async with session_scope() as s:
        await service.add_tag(s, user_id=user_id, kind="phrase", item_id=item_id, tag_name="a")
    async with session_scope() as s:
        token_tags = await service._list_tags(
            s, user_id=user_id, kind="token", item_id=token_id
        )
        assert token_tags == []


async def test_phrase_item_not_found_for_wrong_kind():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _phrase_item(user_id)
    async with session_scope() as s:
        with pytest.raises(service.ItemNotFound):
            await service.put_note(
                s, user_id=user_id, kind="token", item_id=item_id, note_text="x"
            )
