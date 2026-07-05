"""Reader API: tokenized lesson content and reader state (FLQ-4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.lesson_library.models import Lesson
from flinq.modules.reader_state.access import (
    LessonForbidden,
    LessonNotFound,
    LessonNotReady,
    get_readable_lesson,
)
from flinq.modules.reader_state.bulk import (
    ActionAlreadyUndone,
    ActionNotFound,
    bulk_mark_known,
    undo_bulk_action,
)
from flinq.modules.reader_state.content import build_lesson_content
from flinq.modules.reader_state.positions import upsert_position
from flinq.modules.reader_state.schemas import (
    BulkKnownRequest,
    BulkKnownResponse,
    BulkUndoResponse,
    LessonContentResponse,
    ReaderPositionPut,
    TokenStatusesResponse,
)
from flinq.modules.reader_state.statuses import lesson_token_statuses

router = APIRouter(prefix="/api", tags=["reader"])


def _require_user(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user_id


async def _load_lesson(
    session: AsyncSession, lesson_id: uuid.UUID, user_id: uuid.UUID, *, require_ready: bool = True
) -> Lesson:
    try:
        return await get_readable_lesson(session, lesson_id, user_id, require_ready=require_ready)
    except LessonNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    except LessonForbidden:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from None
    except LessonNotReady:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="lesson_not_ready") from None


@router.get("/lessons/{lesson_id}/content", response_model=LessonContentResponse)
async def lesson_content(
    lesson_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LessonContentResponse:
    user_id = _require_user(request)
    lesson = await _load_lesson(session, lesson_id, user_id)
    return await build_lesson_content(session, lesson)


@router.get("/lessons/{lesson_id}/token-statuses", response_model=TokenStatusesResponse)
async def lesson_token_statuses_route(
    lesson_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TokenStatusesResponse:
    user_id = _require_user(request)
    lesson = await _load_lesson(session, lesson_id, user_id)
    statuses = await lesson_token_statuses(session, lesson=lesson, user_id=user_id)
    return TokenStatusesResponse(statuses=statuses)


@router.put("/reader/positions", status_code=status.HTTP_204_NO_CONTENT)
async def put_reader_position(
    body: ReaderPositionPut,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    user_id = _require_user(request)
    # Positions may be written for a lesson still processing (e.g. mode preference).
    await _load_lesson(session, body.lesson_id, user_id, require_ready=False)
    await upsert_position(
        session,
        user_id=user_id,
        lesson_id=body.lesson_id,
        view_mode=body.view_mode,
        current_segment_id=body.current_segment_id,
        current_token_ordinal=body.current_token_ordinal,
    )


@router.post("/reader/bulk-known", response_model=BulkKnownResponse)
async def bulk_known(
    body: BulkKnownRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BulkKnownResponse:
    user_id = _require_user(request)
    lesson = await _load_lesson(session, body.lesson_id, user_id)
    action_id, created_count = await bulk_mark_known(
        session,
        user_id=user_id,
        lesson=lesson,
        from_ordinal=body.from_ordinal,
        to_ordinal=body.to_ordinal,
    )
    return BulkKnownResponse(action_id=action_id, created_count=created_count)


@router.post("/reader/bulk-actions/{action_id}/undo", response_model=BulkUndoResponse)
async def undo_bulk_known(
    action_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BulkUndoResponse:
    user_id = _require_user(request)
    try:
        undone_count = await undo_bulk_action(session, user_id=user_id, action_id=action_id)
    except ActionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    except ActionAlreadyUndone:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="already_undone") from None
    return BulkUndoResponse(undone_count=undone_count)
