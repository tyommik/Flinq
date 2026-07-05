"""On-demand persisted sentence translation («Показать перевод», spec API-6)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.ai_translation import service
from flinq.modules.lesson_library.models import Lesson, LessonSegment
from flinq.modules.reader_state.models import LessonSegmentTranslation


class SegmentNotFound(Exception):  # noqa: N818 -- matches sibling exception naming in this module
    """Segment does not exist, or belongs to a different lesson."""


async def _select_stored(
    session: AsyncSession, *, segment_id: uuid.UUID, target_language_code: str
) -> LessonSegmentTranslation | None:
    return await session.scalar(
        select(LessonSegmentTranslation).where(
            LessonSegmentTranslation.segment_id == segment_id,
            LessonSegmentTranslation.target_language_code == target_language_code,
        )
    )


async def get_or_translate_segment(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    lesson: Lesson,
    segment_id: uuid.UUID,
    target_language_code: str,
) -> tuple[LessonSegmentTranslation, bool]:
    """Return (row, stored) — stored=True means no AI call was needed this request."""
    segment = await session.get(LessonSegment, segment_id)
    if segment is None or segment.lesson_id != lesson.id:
        raise SegmentNotFound

    stored = await _select_stored(
        session, segment_id=segment_id, target_language_code=target_language_code
    )
    if stored is not None:
        return stored, True

    result = await service.translate_sentence(
        session,
        user_id=user_id,
        sentence_text=segment.text,
        target_language_code=target_language_code,
        lesson_id=lesson.id,
    )

    row = LessonSegmentTranslation(
        segment_id=segment_id,
        target_language_code=target_language_code,
        translation_text=result.text,
        source="ai",
        model=result.model,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _select_stored(
            session, segment_id=segment_id, target_language_code=target_language_code
        )
        assert existing is not None  # the conflicting concurrent writer committed it
        return existing, True
    return row, False
