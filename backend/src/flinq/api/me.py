"""User profile endpoints: GET /me, POST /me/onboarding, DELETE /me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.identity.repo import UserRepo
from flinq.modules.identity.schemas import MeResponse

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeResponse)
async def get_me(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> MeResponse:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    user = await UserRepo(session).get_by_id_full(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return MeResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        display_name=user.profile.display_name,
        ui_language_code=user.profile.ui_language_code,
        learning_languages=[ll.language_code for ll in user.learning_languages],
        last_learning_language_code=user.settings.last_learning_language_code,
        needs_onboarding=user.onboarded_at is None,
        onboarded_at=user.onboarded_at,
    )
