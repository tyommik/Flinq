"""Schema invariants: token_items uniqueness + confidence checks, position upsert key."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.identity.repo import UserRepo
from flinq.modules.reader_state.models import ReaderPosition
from flinq.modules.vocabulary.models import TokenItem


@pytest.fixture(autouse=True)
async def _clean(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    yield
    await db_session.execute(delete(TokenItem))
    await db_session.execute(delete(ReaderPosition))
    await db_session.commit()


async def _user(db_session: AsyncSession) -> uuid.UUID:
    user = await UserRepo(db_session).create(
        email=f"rs-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name="T",
        role="learner",
    )
    await db_session.flush()
    return user.id


def _item(user_id: uuid.UUID, **kw: object) -> TokenItem:
    base: dict[str, object] = {
        "user_id": user_id,
        "language_code": "pt",
        "token_text": "edifício",
        "status": "known",
        "confidence": None,
    }
    base.update(kw)
    return TokenItem(**base)  # type: ignore[arg-type]


async def test_token_item_unique_per_user_lang_text(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    db_session.add(_item(user_id))
    await db_session.flush()
    db_session.add(_item(user_id))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_tracked_requires_confidence_and_known_forbids_it(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    db_session.add(_item(user_id, token_text="a", status="tracked", confidence=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
    user_id = await _user(db_session)
    db_session.add(_item(user_id, token_text="b", status="known", confidence=3))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
    user_id = await _user(db_session)
    db_session.add(_item(user_id, token_text="c", status="tracked", confidence=2))
    await db_session.flush()


async def test_reader_position_unique_per_user_lesson(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    from flinq.modules.lesson_library.repo import LessonRepo

    lesson = await LessonRepo(db_session).create_processing_lesson(
        owner_user_id=user_id, title="T", language_code="pt", raw_text="Olá.", visibility="private"
    )
    await db_session.flush()
    db_session.add(ReaderPosition(user_id=user_id, lesson_id=lesson.id, view_mode="page"))
    await db_session.flush()
    db_session.add(ReaderPosition(user_id=user_id, lesson_id=lesson.id, view_mode="sentence"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
