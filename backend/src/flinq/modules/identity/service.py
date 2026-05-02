"""Identity service layer: register/login/logout/onboarding/account deletion."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError

from flinq.core.config import get_settings
from flinq.core.rate_limit import RateLimiter
from flinq.core.security import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    verify_password,
)
from flinq.modules.identity.middleware import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    SESSION_TTL,
)
from flinq.modules.identity.models import User
from flinq.modules.identity.repo import SessionRepo, UserRepo


def _hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(ip.encode()).hexdigest()[:64]


def _set_session_cookies(
    response: Response,
    *,
    session_token: str,
    csrf_token: str,
    persistent: bool,
    secure: bool,
) -> None:
    """Set both session and CSRF cookies. `secure=False` only for dev/test over HTTP."""
    max_age = int(SESSION_TTL.total_seconds()) if persistent else None
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
    )


async def login_user(
    request: Request,
    response: Response,
    *,
    email: str,
    password: str,
    remember_me: bool,
    user_repo: UserRepo,
    session_repo: SessionRepo,
    rate_limiter: RateLimiter,
) -> User:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    rl_key = f"login:{ip}:{email.lower().strip()}"

    if not await rate_limiter.check_and_increment(rl_key):
        retry_after = await rate_limiter.get_retry_after(rl_key)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Retry in {max(retry_after // 60, 1)} min",
            headers={"Retry-After": str(retry_after)},
        )

    user = await user_repo.get_by_email(email)
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    await rate_limiter.reset(rl_key)

    token = generate_session_token()
    csrf = generate_csrf_token()
    await session_repo.create(
        token=token,
        user_id=user.id,
        expires_at=datetime.now(UTC) + SESSION_TTL,
        user_agent=request.headers.get("user-agent"),
        ip_hash=_hash_ip(ip if ip != "unknown" else None),
    )
    _set_session_cookies(
        response,
        session_token=token,
        csrf_token=csrf,
        persistent=remember_me,
        secure=settings.is_prod,
    )
    return user


async def register_user(
    request: Request,
    response: Response,
    *,
    display_name: str,
    email: str,
    password: str,
    user_repo: UserRepo,
    session_repo: SessionRepo,
) -> User:
    settings = get_settings()
    if not settings.allow_public_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")

    role = (
        "admin"
        if settings.initial_admin_email and email.lower() == settings.initial_admin_email.lower()
        else "learner"
    )

    try:
        user = await user_repo.create(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            role=role,
        )
    except IntegrityError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use") from e

    token = generate_session_token()
    csrf = generate_csrf_token()
    await session_repo.create(
        token=token,
        user_id=user.id,
        expires_at=datetime.now(UTC) + SESSION_TTL,
        user_agent=request.headers.get("user-agent"),
        ip_hash=_hash_ip(request.client.host if request.client else None),
    )
    _set_session_cookies(
        response,
        session_token=token,
        csrf_token=csrf,
        persistent=True,
        secure=settings.is_prod,
    )
    return user
