"""Reader API: tokenized lesson content and (later) reader state (FLQ-4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.reader_state.access import (
    LessonForbidden,
    LessonNotFound,
    LessonNotReady,
    get_readable_lesson,
)
from flinq.modules.reader_state.content import build_lesson_content
from flinq.modules.reader_state.schemas import LessonContentResponse, TokenStatusesResponse
from flinq.modules.reader_state.statuses import lesson_token_statuses

router = APIRouter(prefix="/api", tags=["reader"])


def _require_user(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user_id


@router.get("/lessons/{lesson_id}/content", response_model=LessonContentResponse)
async def lesson_content(
    lesson_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LessonContentResponse:
    user_id = _require_user(request)
    try:
        lesson = await get_readable_lesson(session, lesson_id, user_id)
    except LessonNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    except LessonForbidden:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from None
    except LessonNotReady:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="lesson_not_ready") from None
    return await build_lesson_content(session, lesson)


@router.get("/lessons/{lesson_id}/token-statuses", response_model=TokenStatusesResponse)
async def lesson_token_statuses_route(
    lesson_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TokenStatusesResponse:
    user_id = _require_user(request)
    try:
        lesson = await get_readable_lesson(session, lesson_id, user_id)
    except LessonNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    except LessonForbidden:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from None
    except LessonNotReady:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="lesson_not_ready") from None
    statuses = await lesson_token_statuses(session, lesson=lesson, user_id=user_id)
    return TokenStatusesResponse(statuses=statuses)
