"""Lesson repository: list, create, and pipeline-fact persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import (
    Lesson,
    LessonImportJob,
    LessonSegment,
    LessonSource,
    LessonTokenOccurrence,
)


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

    async def create_processing_lesson(
        self,
        *,
        owner_user_id: uuid.UUID,
        title: str,
        language_code: str,
        raw_text: str,
        visibility: str,
    ) -> Lesson:
        lesson = Lesson(
            owner_user_id=owner_user_id,
            title=title,
            language_code=language_code,
            raw_text=raw_text,
            visibility=visibility,
            word_count=0,
            segment_count=0,
            current_source_version=1,
            status="processing",
        )
        self.session.add(lesson)
        await self.session.flush()
        return lesson

    async def add_source(
        self,
        *,
        lesson_id: uuid.UUID,
        content_hash: str,
        source_type: str = "manual",
        version_number: int = 1,
    ) -> LessonSource:
        source = LessonSource(
            lesson_id=lesson_id,
            content_hash=content_hash,
            source_type=source_type,
            version_number=version_number,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def add_import_job(
        self,
        *,
        lesson_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        job_type: str = "import_text",
    ) -> LessonImportJob:
        job = LessonImportJob(
            lesson_id=lesson_id,
            requested_by_user_id=requested_by_user_id,
            job_type=job_type,
            status="pending",
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_lesson(self, lesson_id: uuid.UUID) -> Lesson | None:
        return await self.session.get(Lesson, lesson_id)

    async def lock_lesson(self, lesson_id: uuid.UUID) -> Lesson | None:
        """Fetch a lesson with a row-level lock (FOR UPDATE).

        Serializes concurrent/duplicate import runs for the same lesson so the
        delete-and-recreate of facts cannot interleave.
        """
        stmt = select(Lesson).where(Lesson.id == lesson_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_job(self, job_id: uuid.UUID) -> LessonImportJob | None:
        return await self.session.get(LessonImportJob, job_id)

    async def lock_job(self, job_id: uuid.UUID) -> LessonImportJob | None:
        """Fetch an import job with a row-level lock (FOR UPDATE).

        Lets the worker enforce a single pending/running transition even under
        duplicate task delivery.
        """
        stmt = select(LessonImportJob).where(LessonImportJob.id == job_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def delete_facts(self, lesson_id: uuid.UUID) -> None:
        """Remove all segments + occurrences for a lesson (occurrences first)."""
        await self.session.execute(
            delete(LessonTokenOccurrence).where(LessonTokenOccurrence.lesson_id == lesson_id)
        )
        await self.session.execute(
            delete(LessonSegment).where(LessonSegment.lesson_id == lesson_id)
        )
        await self.session.flush()
