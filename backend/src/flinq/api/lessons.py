"""Lessons API: GET /api/lessons, POST /api/lessons."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.lesson_library import service
from flinq.modules.lesson_library.repo import LessonRepo
from flinq.modules.lesson_library.schemas import (
    CreateLessonRequest,
    LessonListResponse,
    LessonSummary,
)

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


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
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
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


@router.post("", status_code=201, response_model=LessonSummary)
async def create_lesson(
    body: CreateLessonRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LessonSummary:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    lesson = await service.create_lesson_from_text(
        owner_user_id=user_id,
        title=body.title,
        language_code=body.language_code,
        raw_text=body.raw_text,
        visibility=body.visibility,
        repo=LessonRepo(session),
    )
    return LessonSummary.model_validate(lesson)
