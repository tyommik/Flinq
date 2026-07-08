import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo
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
        for model in (PersonalTranslation, PersonalNote, ItemTag, TokenItem):
            await s.execute(delete(model))


async def test_annotation_tables_roundtrip():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = TokenItem(
            user_id=user_id,
            language_code="pt",
            token_text="cada",
            status="tracked",
            confidence=0,
        )
        s.add(item)
        await s.flush()
        s.add(
            PersonalTranslation(
                owner_user_id=user_id,
                item_kind="token",
                item_id=item.id,
                target_language_code="ru",
                translation_text="каждый",
                is_primary=True,
                source_type="user",
            )
        )
        s.add(
            PersonalNote(
                owner_user_id=user_id,
                item_kind="token",
                item_id=item.id,
                note_text="hi",
            )
        )
        s.add(
            ItemTag(
                owner_user_id=user_id,
                item_kind="token",
                item_id=item.id,
                tag_name="verbs",
            )
        )
        await s.flush()

    async with session_scope() as s:
        tr = (await s.execute(select(PersonalTranslation))).scalars().all()
        assert len(tr) == 1 and tr[0].is_primary is True


async def test_lookup_new_returns_new_status():
    async with session_scope() as s:
        user_id = await _make_user(s)
        res = await service.lookup(
            s,
            user_id=user_id,
            language_code="pt",
            text="Cada",
            target_language_code="ru",
        )
    assert res.item_id is None
    assert res.status == "new"
    assert res.confidence is None
    assert res.translations == []


async def test_create_item_tracked_then_patch_to_known():
    async with session_scope() as s:
        user_id = await _make_user(s)
    async with session_scope() as s:
        item = await service.create_item(
            s,
            user_id=user_id,
            kind="token",
            language_code="pt",
            text="cada",
            status="tracked",
            confidence=0,
        )
        item_id = item.id
    async with session_scope() as s:
        res = await service.lookup(
            s,
            user_id=user_id,
            language_code="pt",
            text="cada",
            target_language_code="ru",
        )
        assert res.status == "tracked" and res.confidence == 0
        patched = await service.patch_item(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            status="known",
            confidence=None,
        )
        assert patched.status == "known" and patched.confidence is None


async def test_create_item_is_idempotent_on_unique():
    async with session_scope() as s:
        user_id = await _make_user(s)
    async with session_scope() as s:
        a = await service.create_item(
            s,
            user_id=user_id,
            kind="token",
            language_code="pt",
            text="cada",
            status="tracked",
            confidence=0,
        )
    async with session_scope() as s:
        b = await service.create_item(
            s,
            user_id=user_id,
            kind="token",
            language_code="pt",
            text="cada",
            status="ignored",
            confidence=None,
        )
    assert a.id == b.id and b.status == "ignored"


async def _tracked_item(user_id: uuid.UUID) -> uuid.UUID:
    async with session_scope() as s:
        item = await service.create_item(
            s,
            user_id=user_id,
            kind="token",
            language_code="pt",
            text="cada",
            status="tracked",
            confidence=0,
        )
        return item.id


async def test_add_translation_first_is_primary_next_are_not():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        first, created = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="user",
        )
        assert created is True and first.is_primary is True
    async with session_scope() as s:
        second, created = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="второй",
            source_type="user",
        )
        assert created is True and second.is_primary is False


async def test_add_translation_dedupes_by_text():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        first, _ = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="user",
        )
    async with session_scope() as s:
        again, created = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="dictionary",
        )
    assert created is False and again.id == first.id


async def test_update_translation_changes_text_and_source():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        row, _ = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="dictionary",
        )
        row_id = row.id
    async with session_scope() as s:
        updated = await service.update_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            translation_id=row_id,
            translation_text="поправленный",
        )
        assert updated.translation_text == "поправленный"
        assert updated.source_type == "user"


async def test_update_translation_duplicate_text_raises():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="user",
        )
        second, _ = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="второй",
            source_type="user",
        )
        second_id = second.id
    async with session_scope() as s:
        with pytest.raises(service.DuplicateTranslation):
            await service.update_translation(
                s,
                user_id=user_id,
                kind="token",
                item_id=item_id,
                translation_id=second_id,
                translation_text="первый",
            )


async def test_delete_primary_promotes_earliest_remaining():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        first, _ = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="user",
        )
        first_id = first.id
    async with session_scope() as s:
        await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="второй",
            source_type="user",
        )
    async with session_scope() as s:
        await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="третий",
            source_type="user",
        )
    async with session_scope() as s:
        remaining = await service.delete_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            translation_id=first_id,
        )
    texts = [(t.translation_text, t.is_primary) for t in remaining]
    assert texts == [("второй", True), ("третий", False)]


async def test_delete_translation_foreign_row_raises():
    async with session_scope() as s:
        user_id = await _make_user(s)
        other_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        row, _ = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="user",
        )
        row_id = row.id
    async with session_scope() as s:
        with pytest.raises(service.ItemNotFound):
            await service.delete_translation(
                s,
                user_id=other_id,
                kind="token",
                item_id=item_id,
                translation_id=row_id,
            )


async def test_put_note_upserts():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        await service.put_note(s, user_id=user_id, kind="token", item_id=item_id, note_text="a")
    async with session_scope() as s:
        await service.put_note(s, user_id=user_id, kind="token", item_id=item_id, note_text="b")
    async with session_scope() as s:
        res = await service.lookup(
            s,
            user_id=user_id,
            language_code="pt",
            text="cada",
            target_language_code="ru",
        )
    assert res.note == "b"


async def test_add_and_remove_tag():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        tags = await service.add_tag(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            tag_name="verbs",
        )
        assert tags == ["verbs"]
        # idempotent
        tags = await service.add_tag(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            tag_name="verbs",
        )
        assert tags == ["verbs"]
    async with session_scope() as s:
        tags = await service.remove_tag(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            tag_name="verbs",
        )
        assert tags == []
