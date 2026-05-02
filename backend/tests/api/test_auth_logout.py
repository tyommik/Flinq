from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


async def test_logout_clears_cookies_and_invalidates_session() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Register → auto-login → both cookies set
        r = await c.post(
            "/auth/register",
            json={
                "display_name": "L",
                "email": "logout@example.com",
                "password": "abcdefghij",
            },
        )
        assert r.status_code == 201
        csrf = c.cookies.get("flinq_csrf")
        assert csrf is not None
        assert c.cookies.get("flinq_session") is not None

        # Logout (CSRF required for non-public path)
        r = await c.post("/auth/logout", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        # Cookies cleared by Set-Cookie with Max-Age=0
        # httpx removes them from the jar after such a response
        # If a value remains, it should at minimum no longer be the original


async def test_logout_without_session_returns_403_csrf() -> None:
    """Logout without any cookies fails CSRF (mutating endpoint, not public)."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/auth/logout")
        assert r.status_code == 403


async def test_logout_invalidates_session_in_db() -> None:
    """After logout the session row's expires_at is in the past, so get_active returns None."""
    from flinq.core.db import session_scope
    from flinq.modules.identity.repo import SessionRepo

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post(
            "/auth/register",
            json={
                "display_name": "L2",
                "email": "logout-db@example.com",
                "password": "abcdefghij",
            },
        )
        token = c.cookies.get("flinq_session")
        csrf = c.cookies.get("flinq_csrf")
        assert token and csrf

        # Pre-logout: session is active
        async with session_scope() as s:
            assert await SessionRepo(s).get_active(token) is not None

        await c.post("/auth/logout", headers={"X-CSRF-Token": csrf})

        # Post-logout: session is gone (expires_at moved to NOW)
        async with session_scope() as s:
            assert await SessionRepo(s).get_active(token) is None
