"""Lesson repository: list and create operations."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import Lesson


class LessonRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        lang: str,
        q: str | None = None,
        visibility: str = "all",
        tab: str = "lessons",
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[Lesson], int]:
        # Base: language scope + not archived + visible to user
        stmt = select(Lesson).where(
            Lesson.language_code == lang,
            Lesson.status != "archived",
            or_(
                Lesson.owner_user_id == user_id,
                Lesson.visibility == "shared",
            ),
        )
        if q:
            stmt = stmt.where(Lesson.title.ilike(f"%{q}%"))
        if visibility == "mine":
            stmt = stmt.where(Lesson.owner_user_id == user_id)
        elif visibility == "shared":
            stmt = stmt.where(Lesson.visibility == "shared")

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            stmt.order_by(Lesson.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(
        self,
        *,
        owner_user_id: uuid.UUID,
        title: str,
        language_code: str,
        raw_text: str,
        visibility: str,
        word_count: int,
    ) -> Lesson:
        lesson = Lesson(
            owner_user_id=owner_user_id,
            title=title,
            language_code=language_code,
            raw_text=raw_text,
            visibility=visibility,
            word_count=word_count,
            status="ready",
        )
        self.session.add(lesson)
        await self.session.flush()
        return lesson
