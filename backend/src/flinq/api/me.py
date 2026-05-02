"""User profile endpoints: GET /me, POST /me/onboarding, DELETE /me, PATCH /me/last-language."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.identity import service
from flinq.modules.identity.middleware import CSRF_COOKIE, SESSION_COOKIE
from flinq.modules.identity.repo import UserRepo
from flinq.modules.identity.schemas import (
    DeleteMeRequest,
    MeResponse,
    OnboardingRequest,
    SetLastLanguageRequest,
)

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


@router.post("/onboarding")
async def post_onboarding(
    body: OnboardingRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    first_lang = await service.complete_onboarding(
        user_id,
        ui_language=body.ui_language,
        learning_languages=body.learning_languages,
        translation_language=body.translation_language,
        user_repo=UserRepo(session),
        session=session,
    )
    return {"ok": True, "redirect": f"/learn/{first_lang}/library"}


@router.delete("")
async def delete_me(
    body: DeleteMeRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    await service.delete_me(
        user_id, password=body.password, user_repo=UserRepo(session)
    )
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return {"ok": True}


@router.patch("/last-language")
async def patch_last_language(
    body: SetLastLanguageRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    await service.set_last_language(
        user_id, language_code=body.language_code, user_repo=UserRepo(session)
    )
    return {"ok": True}
