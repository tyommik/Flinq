"""Task registry. Import this module to register all Taskiq tasks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from loguru import logger
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from flinq.core.db import session_scope
from flinq.modules.identity.repo import SessionRepo
from flinq.modules.lesson_library.repo import LessonRepo
from flinq.modules.lesson_library.service import (
    LessonNotProcessableError,
    process_lesson_import,
)
from flinq.worker.broker import broker


@broker.task
async def ping() -> str:
    """Smoke-test task used by tests and health scripts."""
    logger.info("ping task executed")
    return "pong"


@broker.task(schedule=[{"cron": "0 3 * * *"}])  # daily at 03:00
async def cleanup_expired_sessions() -> int:
    """Delete user_sessions rows whose expires_at is in the past (ADR-0008)."""
    async with session_scope() as s:
        deleted = await SessionRepo(s).cleanup_expired()
        if deleted:
            logger.info("cleanup_expired_sessions: removed {} sessions", deleted)
        return deleted


async def run_lesson_import(lesson_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Process an import for an EXACT job, end-to-end. Retry/duplicate-safe.

    Plain async function so tests and a future synchronous path can call it
    without a running worker. The taskiq task simply wraps this. The job row is
    locked FOR UPDATE and only a pending/running job is run, so duplicate task
    delivery becomes a no-op instead of double-processing.
    """
    async with session_scope() as session:
        repo = LessonRepo(session)
        job = await repo.lock_job(job_id)  # FOR UPDATE: serialize deliveries
        if job is None:
            logger.warning("run_lesson_import: job {} not found", job_id)
            return
        if job.status not in {"pending", "running"}:
            logger.info("run_lesson_import: job {} already {}; skipping", job_id, job.status)
            return
        job.status = "running"
        job.started_at = datetime.now(UTC)
        await session.flush()
        try:
            await process_lesson_import(session, lesson_id)
        except LessonNotProcessableError as exc:
            logger.info("run_lesson_import: skipped {} ({})", lesson_id, exc)
            job.status = "done"
            job.finished_at = datetime.now(UTC)
            return
        except Exception as exc:  # record any failure on the job
            logger.exception("run_lesson_import failed for {}", lesson_id)
            lesson = await repo.get_lesson(lesson_id)
            if lesson is not None:
                lesson.status = "failed"
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = datetime.now(UTC)
            return
        job.status = "done"
        job.finished_at = datetime.now(UTC)


@broker.task
async def import_lesson_task(lesson_id: str, job_id: str) -> None:
    """Taskiq entry point: process a lesson import for an exact job."""
    await run_lesson_import(uuid.UUID(lesson_id), uuid.UUID(job_id))


async def enqueue_lesson_import(lesson_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Enqueue the import task. Patched in tests to isolate the API handler."""
    await import_lesson_task.kiq(str(lesson_id), str(job_id))


scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
