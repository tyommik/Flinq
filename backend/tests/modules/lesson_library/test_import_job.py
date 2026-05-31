"""Worker job: success → ready/done, errors → failed, duplicate delivery no-op (AC#4)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.identity.repo import UserRepo
from flinq.modules.lesson_library.models import Lesson, LessonImportJob, LessonTokenOccurrence
from flinq.modules.lesson_library.repo import LessonRepo
from flinq.worker.tasks import run_lesson_import


async def _seed(session: AsyncSession, raw_text: str) -> tuple[uuid.UUID, uuid.UUID]:
    user = await UserRepo(session).create(
        email=f"job-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name="T",
        role="learner",
    )
    await session.flush()
    repo = LessonRepo(session)
    lesson = await repo.create_processing_lesson(
        owner_user_id=user.id,
        title="T",
        language_code="pt",
        raw_text=raw_text,
        visibility="private",
    )
    job = await repo.add_import_job(lesson_id=lesson.id, requested_by_user_id=user.id)
    await session.commit()
    return lesson.id, job.id


async def _occ_count(session: AsyncSession, lesson_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(LessonTokenOccurrence)
        .where(LessonTokenOccurrence.lesson_id == lesson_id)
    )
    return (await session.execute(stmt)).scalar_one()


async def test_job_success_sets_ready_and_done(db_session: AsyncSession) -> None:
    lesson_id, job_id = await _seed(db_session, "Olá mundo. Tudo bem?")

    await run_lesson_import(lesson_id, job_id)

    refreshed = await db_session.get(Lesson, lesson_id)
    job = await db_session.get(LessonImportJob, job_id)
    assert refreshed is not None and refreshed.status == "ready"
    assert job is not None and job.status == "done"
    assert job.finished_at is not None


async def test_job_failure_sets_failed_and_records_error(
    db_session: AsyncSession, monkeypatch
) -> None:
    lesson_id, job_id = await _seed(db_session, "anything")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("segmentation exploded")

    monkeypatch.setattr("flinq.worker.tasks.process_lesson_import", _boom)

    await run_lesson_import(lesson_id, job_id)

    refreshed = await db_session.get(Lesson, lesson_id)
    job = await db_session.get(LessonImportJob, job_id)
    assert refreshed is not None and refreshed.status == "failed"
    assert job is not None and job.status == "failed"
    assert job.error_message and "segmentation exploded" in job.error_message


async def test_duplicate_delivery_is_a_noop(db_session: AsyncSession) -> None:
    """A second delivery of the same (done) job must not double the facts (review #2)."""
    lesson_id, job_id = await _seed(db_session, "Olá mundo. Tudo bem?")

    await run_lesson_import(lesson_id, job_id)
    first = await _occ_count(db_session, lesson_id)

    await run_lesson_import(lesson_id, job_id)

    assert await _occ_count(db_session, lesson_id) == first
    job = await db_session.get(LessonImportJob, job_id)
    assert job is not None and job.status == "done"
