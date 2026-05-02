"""Lesson library service: business logic above the repo."""

from __future__ import annotations

import uuid

from flinq.modules.lesson_library.models import Lesson
from flinq.modules.lesson_library.repo import LessonRepo


def _count_words(text: str) -> int:
    return len(text.split())


async def create_lesson_from_text(
    *,
    owner_user_id: uuid.UUID,
    title: str,
    language_code: str,
    raw_text: str,
    visibility: str,
    repo: LessonRepo,
) -> Lesson:
    return await repo.create(
        owner_user_id=owner_user_id,
        title=title,
        language_code=language_code,
        raw_text=raw_text,
        visibility=visibility,
        word_count=_count_words(raw_text),
    )
