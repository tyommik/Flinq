import pytest
from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


async def test_register_success() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/auth/register",
            json={
                "display_name": "Alice",
                "email": "alice-reg@example.com",
                "password": "abcdefghij",
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert body["needs_onboarding"] is True
        # Both cookies set
        assert c.cookies.get("flinq_session")
        assert c.cookies.get("flinq_csrf")


async def test_register_duplicate_email_409() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post(
            "/auth/register",
            json={
                "display_name": "Bob",
                "email": "bob-dup@example.com",
                "password": "abcdefghij",
            },
        )
        r = await c.post(
            "/auth/register",
            json={
                "display_name": "Bob2",
                "email": "bob-dup@example.com",
                "password": "abcdefghij",
            },
        )
        assert r.status_code == 409


async def test_register_short_password_422() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/auth/register",
            json={
                "display_name": "Short",
                "email": "short@example.com",
                "password": "short",
            },
        )
        assert r.status_code == 422


async def test_register_disabled_returns_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """When FLINQ_ALLOW_PUBLIC_REGISTRATION=false, /auth/register returns 403."""
    from flinq.core.config import get_settings

    monkeypatch.setenv("FLINQ_ALLOW_PUBLIC_REGISTRATION", "false")
    get_settings.cache_clear()
    try:
        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post(
                "/auth/register",
                json={
                    "display_name": "X",
                    "email": "disabled@example.com",
                    "password": "abcdefghij",
                },
            )
            assert r.status_code == 403
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


async def test_register_admin_role_when_email_matches_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """When email matches FLINQ_INITIAL_ADMIN_EMAIL, role is admin."""
    from flinq.core.config import get_settings
    from flinq.core.db import session_scope
    from flinq.modules.identity.repo import UserRepo

    monkeypatch.setenv("FLINQ_INITIAL_ADMIN_EMAIL", "admin-bootstrap@example.com")
    get_settings.cache_clear()
    try:
        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post(
                "/auth/register",
                json={
                    "display_name": "Admin",
                    "email": "admin-bootstrap@example.com",
                    "password": "abcdefghij",
                },
            )
            assert r.status_code == 201

        async with session_scope() as s:
            user = await UserRepo(s).get_by_email("admin-bootstrap@example.com")
            assert user is not None
            assert user.role == "admin"
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
