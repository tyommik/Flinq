"""Auth endpoints: /auth/register, /auth/login, /auth/logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.identity import service
from flinq.modules.identity.repo import SessionRepo, UserRepo
from flinq.modules.identity.schemas import RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    user = await service.register_user(
        request,
        response,
        display_name=body.display_name,
        email=body.email,
        password=body.password,
        user_repo=UserRepo(session),
        session_repo=SessionRepo(session),
    )
    return {"id": str(user.id), "needs_onboarding": True}
