import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.dictionary.models import DictionaryEntry, DictionarySourceVersion
from flinq.modules.identity.repo import UserRepo
from flinq.modules.lesson_library.models import Lesson, LessonSegment, LessonTokenOccurrence
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
        for model in (
            PersonalTranslation,
            PersonalNote,
            ItemTag,
            TokenItem,
            Lesson,  # cascades sources/segments/occurrences via DB FKs
            DictionaryEntry,
            DictionarySourceVersion,
        ):
            await s.execute(delete(model))


async def _item(
    s: AsyncSession,
    user_id: uuid.UUID,
    text: str,
    *,
    lang: str = "pt",
    status: str = "tracked",
    confidence: int | None = 1,
) -> TokenItem:
    item = TokenItem(
        user_id=user_id,
        language_code=lang,
        token_text=text,
        status=status,
        confidence=confidence,
    )
    s.add(item)
    await s.flush()
    return item


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


async def test_list_scopes_by_owner_and_language():
    async with session_scope() as s:
        me = await _make_user(s)
        other = await _make_user(s)
        await _item(s, me, "cada", lang="pt")
        await _item(s, me, "casa", lang="en")  # other language
        await _item(s, other, "porta", lang="pt")  # other user
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=me, language_code="pt", **_defaults())
    assert total == 1
    assert [i.text for i in items] == ["cada"]


async def test_list_filters_status_and_confidence():
    async with session_scope() as s:
        user_id = await _make_user(s)
        await _item(s, user_id, "um", status="tracked", confidence=1)
        await _item(s, user_id, "dois", status="tracked", confidence=3)
        await _item(s, user_id, "tres", status="known", confidence=None)
        await _item(s, user_id, "quatro", status="ignored", confidence=None)
    kw = _defaults()
    kw["statuses"] = ["tracked", "known"]
    kw["confidence_min"] = 2
    kw["confidence_max"] = 4
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    # confidence narrows only tracked rows; known passes regardless (spec §3.1)
    assert total == 2
    assert sorted(i.text for i in items) == ["dois", "tres"]


async def test_list_search_matches_term_and_primary_translation():
    async with session_scope() as s:
        user_id = await _make_user(s)
        a = await _item(s, user_id, "cada")
        await _item(s, user_id, "porta")
        s.add(
            PersonalTranslation(
                owner_user_id=user_id,
                item_kind="token",
                item_id=a.id,
                target_language_code="ru",
                translation_text="каждый",
                is_primary=True,
                source_type="user",
            )
        )
        await s.flush()
    kw = _defaults()
    kw["q"] = "кажд"
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 1 and items[0].text == "cada"
    assert items[0].primary_translation_text == "каждый"
    kw["q"] = "port"
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 1 and items[0].text == "porta"


async def test_list_filters_tags_with_and_semantics():
    async with session_scope() as s:
        user_id = await _make_user(s)
        a = await _item(s, user_id, "cada")
        b = await _item(s, user_id, "porta")
        for item, tag in ((a, "verbs"), (a, "b1"), (b, "verbs")):
            s.add(ItemTag(owner_user_id=user_id, item_kind="token", item_id=item.id, tag_name=tag))
        await s.flush()
    kw = _defaults()
    kw["tags"] = ["verbs", "b1"]
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 1 and items[0].text == "cada"
    assert sorted(items[0].tags) == ["b1", "verbs"]


async def test_list_sort_and_pagination():
    async with session_scope() as s:
        user_id = await _make_user(s)
        for t in ("aaa", "bbb", "ccc"):
            await _item(s, user_id, t)
    kw = _defaults()
    kw["sort"] = "text"
    kw["sort_dir"] = "asc"
    kw["page_size"] = 25
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 3
    assert [i.text for i in items] == ["aaa", "bbb", "ccc"]
    kw["page"] = 2
    kw["page_size"] = 25
    async with session_scope() as s:
        items, _ = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert items == []


async def test_list_added_after():
    async with session_scope() as s:
        user_id = await _make_user(s)
        await _item(s, user_id, "cada")
    cutoff = datetime.now(UTC) + timedelta(days=1)
    kw = _defaults()
    kw["added_after"] = cutoff
    async with session_scope() as s:
        _, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 0


async def test_list_enriches_context_and_pos():
    async with session_scope() as s:
        user_id = await _make_user(s)
        await _item(s, user_id, "cada")
        lesson = Lesson(
            owner_user_id=user_id,
            language_code="pt",
            title="L",
            raw_text="Cada casa.",
            status="ready",
        )
        s.add(lesson)
        await s.flush()
        seg = LessonSegment(
            lesson_id=lesson.id,
            ordinal=0,
            segment_type="sentence",
            text="Cada casa tem uma porta.",
            start_char_offset=0,
            end_char_offset=24,
        )
        s.add(seg)
        await s.flush()
        s.add(
            LessonTokenOccurrence(
                lesson_id=lesson.id,
                segment_id=seg.id,
                ordinal_in_lesson=0,
                ordinal_in_segment=0,
                surface_text="Cada",
                normalized_text="cada",
                start_char_offset=0,
                end_char_offset=4,
                is_word_like=True,
            )
        )
        version = DictionarySourceVersion(
            source_name="kaikki",
            source_language_code="pt",
            target_language_code="ru",
            source_version="v1",
            status="active",
        )
        s.add(version)
        await s.flush()
        s.add(
            DictionaryEntry(
                source_version_id=version.id,
                source_language_code="pt",
                headword="cada",
                headword_normalized="cada",
                part_of_speech="det",
                entry_key="cada:det",
            )
        )
        await s.flush()
    async with session_scope() as s:
        items, _ = await service.list_items(s, user_id=user_id, language_code="pt", **_defaults())
    assert items[0].context == "Cada casa tem uma porta."
    assert items[0].pos == "det"


async def test_list_nulls_when_no_enrichment():
    async with session_scope() as s:
        user_id = await _make_user(s)
        await _item(s, user_id, "cada")
    async with session_scope() as s:
        items, _ = await service.list_items(s, user_id=user_id, language_code="pt", **_defaults())
    it = items[0]
    assert it.primary_translation_text is None
    assert it.context is None and it.pos is None and it.tags == []
