"""Lesson access rule shared by all reader endpoints."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import Lesson


class LessonNotFound(Exception): ...  # noqa: N818 — reused verbatim by Tasks 3-6


class LessonForbidden(Exception): ...  # noqa: N818 — reused verbatim by Tasks 3-6


class LessonNotReady(Exception): ...  # noqa: N818 — reused verbatim by Tasks 3-6


async def get_readable_lesson(
    session: AsyncSession, lesson_id: uuid.UUID, user_id: uuid.UUID, *, require_ready: bool = True
) -> Lesson:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise LessonNotFound
    if lesson.visibility != "shared" and lesson.owner_user_id != user_id:
        raise LessonForbidden
    if require_ready and lesson.status != "ready":
        raise LessonNotReady
    return lesson
