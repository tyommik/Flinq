"""PhraseItem: roundtrip + DB constraints (uniqueness, 2-8 words)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo
from flinq.modules.vocabulary.models import PhraseItem


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
        await s.execute(delete(PhraseItem))


def _phrase(user_id: uuid.UUID, text: str = "so far so good") -> PhraseItem:
    return PhraseItem(
        user_id=user_id,
        language_code="en",
        phrase_text=text,
        display_text="So far, so good",
        status="tracked",
        confidence=1,
    )


async def test_roundtrip():
    async with session_scope() as s:
        user_id = await _make_user(s)
        s.add(_phrase(user_id))
        await s.flush()
        row = (await s.execute(select(PhraseItem))).scalar_one()
        assert row.phrase_text == "so far so good"
        assert row.added_by == "user"


async def test_unique_user_lang_text():
    async with session_scope() as s:
        user_id = await _make_user(s)
        s.add(_phrase(user_id))
        await s.flush()
        s.add(_phrase(user_id))
        with pytest.raises(IntegrityError):
            await s.flush()
        await s.rollback()


async def test_word_count_check_rejects_single_word():
    async with session_scope() as s:
        user_id = await _make_user(s)
        s.add(_phrase(user_id, text="alone"))
        with pytest.raises(IntegrityError):
            await s.flush()
        await s.rollback()


async def test_word_count_check_rejects_nine_words():
    async with session_scope() as s:
        user_id = await _make_user(s)
        s.add(_phrase(user_id, text="a b c d e f g h i"))
        with pytest.raises(IntegrityError):
            await s.flush()
        await s.rollback()
