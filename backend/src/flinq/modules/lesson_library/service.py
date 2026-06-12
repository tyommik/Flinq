"""Lesson library service: lesson creation and the import pipeline."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import (
    Lesson,
    LessonSegment,
    LessonTokenOccurrence,
)
from flinq.modules.lesson_library.repo import LessonRepo
from flinq.modules.lesson_library.tokenization import RegexSegmenter, tokenize

# Lesson statuses from which (re)processing is allowed. A `ready` lesson is
# immutable (domain model §14.1), so it is never reprocessed.
_PROCESSABLE = {"processing", "failed"}


class LessonNotFoundError(Exception):
    """Raised when a lesson id does not exist."""


class LessonNotProcessableError(Exception):
    """Raised when import is attempted on a lesson that is not re-runnable."""


def _normalize_newlines(raw_text: str) -> str:
    """Canonicalize line endings to \\n so offsets and segmentation are stable."""
    return raw_text.replace("\r\n", "\n").replace("\r", "\n")


def content_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


async def create_lesson_for_import(
    *,
    owner_user_id: uuid.UUID,
    title: str,
    language_code: str,
    raw_text: str,
    visibility: str,
    repo: LessonRepo,
) -> tuple[Lesson, uuid.UUID]:
    """Create a processing lesson + v1 source + pending job. Returns (lesson, job_id)."""
    canonical = _normalize_newlines(raw_text)
    lesson = await repo.create_processing_lesson(
        owner_user_id=owner_user_id,
        title=title,
        language_code=language_code,
        raw_text=canonical,
        visibility=visibility,
    )
    await repo.add_source(lesson_id=lesson.id, content_hash=content_hash(canonical))
    job = await repo.add_import_job(lesson_id=lesson.id, requested_by_user_id=owner_user_id)
    return lesson, job.id


async def mark_import_failed(
    session: AsyncSession,
    *,
    lesson_id: uuid.UUID,
    job_id: uuid.UUID,
    error: str,
) -> None:
    """Flip a lesson + its import job to failed (used when enqueue cannot happen).

    Never downgrades a lesson that already reached ready. Caller commits.
    """
    repo = LessonRepo(session)
    lesson = await repo.get_lesson(lesson_id)
    if lesson is not None and lesson.status != "ready":
        lesson.status = "failed"
    job = await repo.get_job(job_id)
    if job is not None:
        job.status = "failed"
        job.error_message = error
        job.finished_at = datetime.now(UTC)
    await session.flush()


async def process_lesson_import(session: AsyncSession, lesson_id: uuid.UUID) -> None:
    """Segment + tokenize a lesson's text into facts, then mark it ready.

    Idempotent and concurrency-safe: the lesson row is locked FOR UPDATE and its
    status re-checked under the lock, so duplicate/concurrent runs serialize and
    a ready lesson is never mutated. Existing facts are deleted before re-insert.
    Allowed only while the lesson status is in {processing, failed}.
    """
    repo = LessonRepo(session)
    lesson = await repo.lock_lesson(lesson_id)  # FOR UPDATE: serialize concurrent runs
    if lesson is None:
        raise LessonNotFoundError(str(lesson_id))
    if lesson.status not in _PROCESSABLE:  # re-checked while holding the row lock
        raise LessonNotProcessableError(f"lesson {lesson_id} is {lesson.status}")

    await repo.delete_facts(lesson_id)

    segmenter = RegexSegmenter(lesson.language_code)
    word_count = 0
    segment_ordinal = 0
    occ_ordinal = 0

    for paragraph in segmenter.split_paragraphs(lesson.raw_text):
        for sentence in segmenter.split_sentences(paragraph.text, base_offset=paragraph.start):
            segment = LessonSegment(
                lesson_id=lesson_id,
                ordinal=segment_ordinal,
                segment_type="sentence",
                text=sentence.text,
                start_char_offset=sentence.start,
                end_char_offset=sentence.end,
            )
            session.add(segment)
            await session.flush()  # assign segment.id for the occurrence FK

            for seg_idx, tok in enumerate(tokenize(sentence.text, base_offset=sentence.start)):
                session.add(
                    LessonTokenOccurrence(
                        lesson_id=lesson_id,
                        segment_id=segment.id,
                        ordinal_in_lesson=occ_ordinal,
                        ordinal_in_segment=seg_idx,
                        surface_text=tok.surface_text,
                        normalized_text=tok.normalized_text,
                        start_char_offset=tok.start_char_offset,
                        end_char_offset=tok.end_char_offset,
                        is_word_like=tok.is_word_like,
                    )
                )
                occ_ordinal += 1
                if tok.is_word_like:
                    word_count += 1

            segment_ordinal += 1

    lesson.word_count = word_count
    lesson.segment_count = segment_ordinal
    lesson.status = "ready"
    await session.flush()
