import pytest
from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


async def _register(c: AsyncClient, *, email: str, password: str = "abcdefghij") -> None:
    r = await c.post(
        "/auth/register",
        json={"display_name": "T", "email": email, "password": password},
    )
    assert r.status_code == 201, r.text


async def test_login_success() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, email="login-ok@example.com")
        # Clear cookies from registration auto-login to test login fresh
        c.cookies.clear()
        r = await c.post(
            "/auth/login",
            json={
                "email": "login-ok@example.com",
                "password": "abcdefghij",
                "remember_me": True,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "id" in body
        assert body["needs_onboarding"] is True
        assert c.cookies.get("flinq_session")
        assert c.cookies.get("flinq_csrf")


async def test_login_wrong_password_returns_401() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register(c, email="login-bad-pw@example.com")
        c.cookies.clear()
        r = await c.post(
            "/auth/login",
            json={
                "email": "login-bad-pw@example.com",
                "password": "wrongpassword",
                "remember_me": False,
            },
        )
        assert r.status_code == 401
        assert "Invalid email or password" in r.json()["detail"]


async def test_login_unknown_email_returns_401() -> None:
    """Anti-enumeration: unknown email returns same 401 as wrong password."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/auth/login",
            json={
                "email": "nobody@example.com",
                "password": "abcdefghij",
                "remember_me": False,
            },
        )
        assert r.status_code == 401
        assert "Invalid email or password" in r.json()["detail"]


async def test_login_rate_limit_after_n_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """After login_max_attempts failures, next attempt returns 429."""
    from flinq.core.config import get_settings

    monkeypatch.setenv("FLINQ_LOGIN_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("FLINQ_LOGIN_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    try:
        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await _register(c, email="rl@example.com")
            c.cookies.clear()
            for _ in range(3):
                r = await c.post(
                    "/auth/login",
                    json={
                        "email": "rl@example.com",
                        "password": "wrong",
                        "remember_me": False,
                    },
                )
                assert r.status_code == 401
            # 4th attempt → 429
            r = await c.post(
                "/auth/login",
                json={
                    "email": "rl@example.com",
                    "password": "wrong",
                    "remember_me": False,
                },
            )
            assert r.status_code == 429
            assert "Retry-After" in r.headers
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


async def test_login_resets_rate_limit_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful login clears the rate-limit counter."""
    from flinq.core.config import get_settings

    monkeypatch.setenv("FLINQ_LOGIN_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("FLINQ_LOGIN_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    try:
        transport = ASGITransport(app=create_app())
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await _register(c, email="reset@example.com")
            c.cookies.clear()
            # 2 fails
            for _ in range(2):
                r = await c.post(
                    "/auth/login",
                    json={
                        "email": "reset@example.com",
                        "password": "wrong",
                        "remember_me": False,
                    },
                )
                assert r.status_code == 401
            # success — should reset counter
            r = await c.post(
                "/auth/login",
                json={
                    "email": "reset@example.com",
                    "password": "abcdefghij",
                    "remember_me": False,
                },
            )
            assert r.status_code == 200
            c.cookies.clear()
            # 3 more fails should NOT trigger 429 (counter was reset)
            for _ in range(3):
                r = await c.post(
                    "/auth/login",
                    json={
                        "email": "reset@example.com",
                        "password": "wrong",
                        "remember_me": False,
                    },
                )
                assert r.status_code == 401
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
