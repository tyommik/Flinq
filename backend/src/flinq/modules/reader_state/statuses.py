"""Per-lesson token status map: the user's TokenItems ∩ the lesson's words."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import Lesson, LessonTokenOccurrence
from flinq.modules.reader_state.schemas import TokenStatusOut
from flinq.modules.vocabulary.models import TokenItem


async def lesson_token_statuses(
    session: AsyncSession, *, lesson: Lesson, user_id: uuid.UUID
) -> dict[str, TokenStatusOut]:
    lesson_words = (
        select(LessonTokenOccurrence.normalized_text)
        .where(
            LessonTokenOccurrence.lesson_id == lesson.id,
            LessonTokenOccurrence.is_word_like.is_(True),
        )
        .distinct()
        .scalar_subquery()
    )
    rows = await session.execute(
        select(TokenItem.token_text, TokenItem.status, TokenItem.confidence).where(
            TokenItem.user_id == user_id,
            TokenItem.language_code == lesson.language_code,
            TokenItem.token_text.in_(lesson_words),
        )
    )
    return {text: TokenStatusOut(s=status, c=confidence) for text, status, confidence in rows.all()}
