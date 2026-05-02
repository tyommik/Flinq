from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.main import create_app
from flinq.modules.identity.middleware import CSRF_COOKIE


async def test_no_cookie_state_is_none(db_session: AsyncSession) -> None:
    """Without session cookie, request.state.user_id stays None — health endpoint still works."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200


async def test_csrf_blocks_post_without_header(db_session: AsyncSession) -> None:
    """POST to a non-public path without CSRF token returns 403."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # /me is not yet implemented — but CSRFMiddleware runs BEFORE routing,
        # so we can use any non-PUBLIC_PATHS POST and expect 403 (not 404).
        r = await c.post("/me/anything", json={})
        assert r.status_code == 403
        assert "CSRF" in r.json().get("detail", "")


async def test_csrf_allows_post_when_header_matches_cookie(db_session: AsyncSession) -> None:
    """POST with matching X-CSRF-Token + flinq_csrf cookie passes CSRF check; route returns 404."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.cookies.set(CSRF_COOKIE, "abc")
        r = await c.post("/me/anything", json={}, headers={"X-CSRF-Token": "abc"})
        # /me/anything doesn't exist → 404 (CSRF passed)
        assert r.status_code == 404


async def test_csrf_skipped_for_public_paths() -> None:
    """POST /auth/register and /auth/login are PUBLIC_PATHS — no CSRF needed."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # /auth/register doesn't exist yet → 404, but CSRF should be skipped
        r = await c.post("/auth/register", json={})
        assert r.status_code == 404  # not 403


async def test_csrf_skipped_for_get_requests() -> None:
    """GET requests bypass CSRF entirely."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200
