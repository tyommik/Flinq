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


async def _item(s: AsyncSession, user_id: uuid.UUID, text: str) -> TokenItem:
    item = TokenItem(
        user_id=user_id, language_code="pt", token_text=text, status="tracked", confidence=1
    )
    s.add(item)
    await s.flush()
    return item


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    async with session_scope() as s:
        for model in (PersonalTranslation, PersonalNote, ItemTag, TokenItem):
            await s.execute(delete(model))


async def test_bulk_set_known_and_skips_foreign():
    async with session_scope() as s:
        me = await _make_user(s)
        other = await _make_user(s)
        mine = await _item(s, me, "cada")
        foreign = await _item(s, other, "porta")
        mine_id, foreign_id = mine.id, foreign.id
    async with session_scope() as s:
        affected = await service.bulk_action(
            s,
            user_id=me,
            item_ids=[mine_id, foreign_id, uuid.uuid4()],
            action="set_known",
            tag_name=None,
        )
    assert affected == 1
    async with session_scope() as s:
        mine_db = await s.get(TokenItem, mine_id)
        foreign_db = await s.get(TokenItem, foreign_id)
        assert mine_db is not None and mine_db.status == "known"
        assert mine_db.confidence is None
        assert foreign_db is not None and foreign_db.status == "tracked"


async def test_bulk_delete_cascades_annotations():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = await _item(s, user_id, "cada")
        item_id = item.id
        s.add(
            PersonalTranslation(
                owner_user_id=user_id,
                item_kind="token",
                item_id=item_id,
                target_language_code="ru",
                translation_text="каждый",
                is_primary=True,
                source_type="user",
            )
        )
        s.add(
            PersonalNote(owner_user_id=user_id, item_kind="token", item_id=item_id, note_text="n")
        )
        s.add(ItemTag(owner_user_id=user_id, item_kind="token", item_id=item_id, tag_name="verbs"))
        await s.flush()
    async with session_scope() as s:
        affected = await service.bulk_action(
            s, user_id=user_id, item_ids=[item_id], action="delete", tag_name=None
        )
    assert affected == 1
    async with session_scope() as s:
        assert await s.get(TokenItem, item_id) is None
        for model in (PersonalTranslation, PersonalNote, ItemTag):
            left = (await s.execute(select(model))).scalars().all()
            assert left == []


async def test_bulk_add_tag_idempotent():
    async with session_scope() as s:
        user_id = await _make_user(s)
        a = await _item(s, user_id, "cada")
        b = await _item(s, user_id, "porta")
        s.add(ItemTag(owner_user_id=user_id, item_kind="token", item_id=a.id, tag_name="b1"))
        await s.flush()
        a_id, b_id = a.id, b.id
    async with session_scope() as s:
        affected = await service.bulk_action(
            s, user_id=user_id, item_ids=[a_id, b_id], action="add_tag", tag_name="b1"
        )
    assert affected == 2
    async with session_scope() as s:
        rows = (await s.execute(select(ItemTag.item_id, ItemTag.tag_name))).all()
    assert sorted(str(r[0]) for r in rows) == sorted([str(a_id), str(b_id)])
