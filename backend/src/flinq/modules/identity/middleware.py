"""Session and CSRF middleware (ADR-0008).

Reads session cookie, hydrates `request.state.user_id` and `request.state.session_token`.
For mutating methods, validates `X-CSRF-Token` header against `flinq_csrf` cookie.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from flinq.core.db import session_scope
from flinq.modules.identity.repo import SessionRepo

SESSION_COOKIE = "flinq_session"
CSRF_COOKIE = "flinq_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL = timedelta(days=30)
TOUCH_INTERVAL = timedelta(minutes=5)
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PUBLIC_PATHS = frozenset({"/health", "/auth/register", "/auth/login"})


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.user_id = None
        request.state.session_token = None

        token = request.cookies.get(SESSION_COOKIE)
        if token:
            async with session_scope() as s:
                sess = await SessionRepo(s).get_active(token)
                if sess is not None:
                    request.state.user_id = sess.user_id
                    request.state.session_token = token
                    last_seen = sess.last_seen_at
                    if last_seen.tzinfo is None:
                        last_seen = last_seen.replace(tzinfo=UTC)
                    if datetime.now(UTC) - last_seen > TOUCH_INTERVAL:
                        await SessionRepo(s).touch(
                            token,
                            new_expires_at=datetime.now(UTC) + SESSION_TTL,
                        )

        return await call_next(request)


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method in MUTATING_METHODS and request.url.path not in PUBLIC_PATHS:
            cookie = request.cookies.get(CSRF_COOKIE)
            header = request.headers.get(CSRF_HEADER)
            if not cookie or cookie != header:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token mismatch"},
                )
        return await call_next(request)
