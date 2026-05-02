from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


async def _register(c: AsyncClient, email: str) -> str:
    r = await c.post(
        "/auth/register",
        json={"display_name": "T", "email": email, "password": "abcdefghij"},
    )
    assert r.status_code == 201
    return c.cookies.get("flinq_csrf")  # type: ignore[return-value]


async def test_delete_me_with_correct_password() -> None:
    from flinq.core.db import session_scope
    from flinq.modules.identity.repo import UserRepo

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register(c, "delete-ok@example.com")

        r = await c.request(
            "DELETE",
            "/me",
            json={"password": "abcdefghij"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        # User actually deleted
        async with session_scope() as s:
            user = await UserRepo(s).get_by_email("delete-ok@example.com")
            assert user is None


async def test_delete_me_wrong_password_returns_401() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register(c, "delete-bad@example.com")

        r = await c.request(
            "DELETE",
            "/me",
            json={"password": "wrong"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 401


async def test_delete_me_without_session_returns_403() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.request("DELETE", "/me", json={"password": "x"})
        assert r.status_code == 403  # CSRF
