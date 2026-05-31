"""Lessons API: list, async import (202 + enqueue), and status polling."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.lesson_library import service
from flinq.modules.lesson_library.repo import LessonRepo
from flinq.modules.lesson_library.schemas import (
    CreateLessonRequest,
    LessonCreatedResponse,
    LessonListResponse,
    LessonStatusResponse,
    LessonSummary,
)
from flinq.worker.tasks import enqueue_lesson_import

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


def _require_user(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user_id


@router.get("", response_model=LessonListResponse)
async def list_lessons(
    request: Request,
    lang: str,
    tab: str = "lessons",
    q: str | None = None,
    visibility: str = "all",
    page: int = 1,
    page_size: int = 25,
    session: AsyncSession = Depends(get_session),
) -> LessonListResponse:
    user_id = _require_user(request)
    items, total = await LessonRepo(session).list_for_user(
        user_id=user_id,
        lang=lang,
        q=q,
        visibility=visibility,
        tab=tab,
        page=page,
        page_size=page_size,
    )
    return LessonListResponse(
        items=[LessonSummary.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=LessonCreatedResponse)
async def create_lesson(
    body: CreateLessonRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LessonCreatedResponse:
    user_id = _require_user(request)
    lesson, job_id = await service.create_lesson_for_import(
        owner_user_id=user_id,
        title=body.title,
        language_code=body.language_code,
        raw_text=body.raw_text,
        visibility=body.visibility,
        repo=LessonRepo(session),
    )
    lesson_id = lesson.id
    lesson_status = lesson.status
    # Commit so the background worker (which opens its own session) sees the rows.
    await session.commit()
    # If the queue is unavailable, do NOT strand the lesson in `processing`
    # forever: mark it failed and surface a 503 so the client can retry.
    try:
        await enqueue_lesson_import(lesson_id, job_id)
    except Exception as exc:  # any enqueue/transport failure must not strand the lesson
        logger.warning("enqueue_lesson_import failed for {}: {}", lesson_id, exc)
        await service.mark_import_failed(
            session, lesson_id=lesson_id, job_id=job_id, error=f"enqueue failed: {exc}"
        )
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "could not queue lesson import"
        ) from exc
    return LessonCreatedResponse(id=lesson_id, status=lesson_status)


@router.get("/{lesson_id}", response_model=LessonStatusResponse)
async def get_lesson(
    lesson_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LessonStatusResponse:
    user_id = _require_user(request)
    lesson = await LessonRepo(session).get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if lesson.owner_user_id != user_id and lesson.visibility != "shared":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return LessonStatusResponse.model_validate(lesson)
