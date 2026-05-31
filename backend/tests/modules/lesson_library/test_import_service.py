"""Import service: round-trip, ordering, idempotency, immutability (AC#5, AC#6)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.identity.repo import UserRepo
from flinq.modules.lesson_library import service
from flinq.modules.lesson_library.models import (
    Lesson,
    LessonSegment,
    LessonTokenOccurrence,
)
from flinq.modules.lesson_library.repo import LessonRepo

TEXT = "Olá mundo. Como vai você?\n\nTudo bem aqui."


async def _make_processing_lesson(session: AsyncSession) -> uuid.UUID:
    user = await UserRepo(session).create(
        email=f"imp-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name="T",
        role="learner",
    )
    await session.flush()
    lesson = await LessonRepo(session).create_processing_lesson(
        owner_user_id=user.id,
        title="T",
        language_code="pt",
        raw_text=TEXT,
        visibility="private",
    )
    await session.flush()
    return lesson.id


async def _count(session: AsyncSession, model, lesson_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(model).where(model.lesson_id == lesson_id)
    return (await session.execute(stmt)).scalar_one()


async def test_round_trip_marks_ready_and_creates_facts(db_session: AsyncSession) -> None:
    lesson_id = await _make_processing_lesson(db_session)

    await service.process_lesson_import(db_session, lesson_id)

    lesson = await db_session.get(Lesson, lesson_id)
    assert lesson is not None
    assert lesson.status == "ready"
    assert lesson.segment_count == await _count(db_session, LessonSegment, lesson_id)
    assert lesson.word_count > 0
    assert await _count(db_session, LessonTokenOccurrence, lesson_id) > 0


async def test_occurrence_ordinals_are_unique_and_ordered(db_session: AsyncSession) -> None:
    lesson_id = await _make_processing_lesson(db_session)
    await service.process_lesson_import(db_session, lesson_id)

    stmt = (
        select(LessonTokenOccurrence.ordinal_in_lesson)
        .where(LessonTokenOccurrence.lesson_id == lesson_id)
        .order_by(LessonTokenOccurrence.ordinal_in_lesson)
    )
    ordinals = [row[0] for row in (await db_session.execute(stmt)).all()]
    assert ordinals == list(range(len(ordinals)))


async def test_retry_is_idempotent(db_session: AsyncSession) -> None:
    lesson_id = await _make_processing_lesson(db_session)

    await service.process_lesson_import(db_session, lesson_id)
    occ_first = await _count(db_session, LessonTokenOccurrence, lesson_id)
    seg_first = await _count(db_session, LessonSegment, lesson_id)

    lesson = await db_session.get(Lesson, lesson_id)
    assert lesson is not None
    lesson.status = "failed"
    await db_session.flush()
    await service.process_lesson_import(db_session, lesson_id)

    assert await _count(db_session, LessonTokenOccurrence, lesson_id) == occ_first
    assert await _count(db_session, LessonSegment, lesson_id) == seg_first


async def test_ready_lesson_is_not_reprocessed(db_session: AsyncSession) -> None:
    lesson_id = await _make_processing_lesson(db_session)
    await service.process_lesson_import(db_session, lesson_id)

    with pytest.raises(service.LessonNotProcessableError):
        await service.process_lesson_import(db_session, lesson_id)
