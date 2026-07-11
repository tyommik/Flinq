import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo
from flinq.modules.lesson_library.models import Lesson, LessonSegment, LessonTokenOccurrence
from flinq.modules.reader_state import bulk
from flinq.modules.reader_state.models import BulkAction
from flinq.modules.vocabulary import service
from flinq.modules.vocabulary.models import ItemTag, PersonalNote, PersonalTranslation, TokenItem


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
        for model in (PersonalTranslation, PersonalNote, ItemTag, TokenItem, BulkAction, Lesson):
            await s.execute(delete(model))


async def _lesson_with_words(s: AsyncSession, user_id: uuid.UUID, words: list[str]) -> Lesson:
    lesson = Lesson(
        owner_user_id=user_id,
        language_code="pt",
        title="L",
        raw_text=" ".join(words),
        status="ready",
    )
    s.add(lesson)
    await s.flush()
    seg = LessonSegment(
        lesson_id=lesson.id,
        ordinal=0,
        segment_type="sentence",
        text=" ".join(words),
        start_char_offset=0,
        end_char_offset=100,
    )
    s.add(seg)
    await s.flush()
    for i, w in enumerate(words):
        s.add(
            LessonTokenOccurrence(
                lesson_id=lesson.id,
                segment_id=seg.id,
                ordinal_in_lesson=i,
                ordinal_in_segment=i,
                surface_text=w,
                normalized_text=w,
                start_char_offset=0,
                end_char_offset=1,
                is_word_like=True,
            )
        )
    await s.flush()
    return lesson


async def test_bulk_known_creates_bulk_provenance():
    async with session_scope() as s:
        user_id = await _make_user(s)
        lesson = await _lesson_with_words(s, user_id, ["cada", "porta"])
        await bulk.bulk_mark_known(s, user_id=user_id, lesson=lesson, from_ordinal=0, to_ordinal=1)
    async with session_scope() as s:
        rows = (await s.execute(select(TokenItem))).scalars().all()
    assert len(rows) == 2
    assert all(r.added_by == "bulk" for r in rows)


async def test_bulk_known_leaves_existing_user_item_untouched():
    async with session_scope() as s:
        user_id = await _make_user(s)
        s.add(
            TokenItem(
                user_id=user_id,
                language_code="pt",
                token_text="cada",
                status="tracked",
                confidence=2,
            )
        )
        await s.flush()
        lesson = await _lesson_with_words(s, user_id, ["cada"])
        await bulk.bulk_mark_known(s, user_id=user_id, lesson=lesson, from_ordinal=0, to_ordinal=0)
    async with session_scope() as s:
        row = (await s.execute(select(TokenItem))).scalar_one()
    assert row.added_by == "user" and row.status == "tracked" and row.confidence == 2


async def test_undo_skips_user_claimed_items():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = TokenItem(
            user_id=user_id,
            language_code="pt",
            token_text="cada",
            status="known",
            confidence=None,
            added_by="user",
        )
        s.add(item)
        await s.flush()
        action = BulkAction(
            user_id=user_id,
            lesson_id=(await _lesson_with_words(s, user_id, ["x"])).id,
            action_type="bulk_known",
            page_fingerprint="0:0",
            payload_json={"token_item_ids": [str(item.id)]},
        )
        s.add(action)
        await s.flush()
        action_id, item_id = action.id, item.id
    async with session_scope() as s:
        undone = await bulk.undo_bulk_action(s, user_id=user_id, action_id=action_id)
    assert undone == 0
    async with session_scope() as s:
        assert await s.get(TokenItem, item_id) is not None


def _defaults() -> dict[str, Any]:
    return {
        "target_language_code": "ru",
        "kind": "all",
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
    }


async def _bulk_item(s: AsyncSession, user_id: uuid.UUID, text: str = "cada") -> TokenItem:
    item = TokenItem(
        user_id=user_id,
        language_code="pt",
        token_text=text,
        status="known",
        confidence=None,
        added_by="bulk",
    )
    s.add(item)
    await s.flush()
    return item


async def test_patch_item_promotes_to_user():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = await _bulk_item(s, user_id)
        item_id = item.id
    async with session_scope() as s:
        await service.patch_item(
            s, user_id=user_id, kind="token", item_id=item_id, status="tracked", confidence=2
        )
    async with session_scope() as s:
        row = await s.get(TokenItem, item_id)
        assert row is not None and row.added_by == "user"


async def test_create_item_over_bulk_promotes():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = await _bulk_item(s, user_id)
        item_id = item.id
    async with session_scope() as s:
        await service.create_item(
            s,
            user_id=user_id,
            kind="token",
            language_code="pt",
            text="cada",
            status="tracked",
            confidence=0,
        )
    async with session_scope() as s:
        row = await s.get(TokenItem, item_id)
        assert row is not None and row.added_by == "user"


async def test_annotation_promotes_to_user():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = await _bulk_item(s, user_id)
        item_id = item.id
    async with session_scope() as s:
        await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="каждый",
            source_type="user",
        )
    async with session_scope() as s:
        row = await s.get(TokenItem, item_id)
        assert row is not None and row.added_by == "user"


async def test_bulk_action_promotes_to_user():
    async with session_scope() as s:
        user_id = await _make_user(s)
        a = await _bulk_item(s, user_id, "cada")
        b = await _bulk_item(s, user_id, "porta")
        ids = [a.id, b.id]
    async with session_scope() as s:
        await service.bulk_action(
            s, user_id=user_id, item_ids=ids, action="set_ignored", tag_name=None
        )
    async with session_scope() as s:
        rows = (await s.execute(select(TokenItem))).scalars().all()
    assert all(r.added_by == "user" for r in rows)


async def test_list_items_filters_added_by():
    async with session_scope() as s:
        user_id = await _make_user(s)
        await _bulk_item(s, user_id, "cada")
        s.add(
            TokenItem(
                user_id=user_id,
                language_code="pt",
                token_text="porta",
                status="tracked",
                confidence=1,
            )
        )
        await s.flush()
    kw = _defaults()  # reuse the Task-1-file defaults helper or copy from test_vocabulary_list.py
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 1 and items[0].text == "porta"
    kw["added_by"] = "all"
    async with session_scope() as s:
        _, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 2
