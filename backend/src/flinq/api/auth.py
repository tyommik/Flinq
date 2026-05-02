"""Auth endpoints: /auth/register, /auth/login, /auth/logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.config import get_settings
from flinq.core.db import get_session
from flinq.core.rate_limit import RateLimiter
from flinq.core.redis import get_redis
from flinq.modules.identity import service
from flinq.modules.identity.repo import SessionRepo, UserRepo
from flinq.modules.identity.schemas import LoginRequest, RegisterRequest

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


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict[str, object]:
    settings = get_settings()
    rl = RateLimiter(
        redis,
        max_attempts=settings.login_max_attempts,
        window_seconds=settings.login_window_seconds,
    )
    user = await service.login_user(
        request,
        response,
        email=body.email,
        password=body.password,
        remember_me=body.remember_me,
        user_repo=UserRepo(session),
        session_repo=SessionRepo(session),
        rate_limiter=rl,
    )
    return {
        "id": str(user.id),
        "needs_onboarding": user.onboarded_at is None,
    }
