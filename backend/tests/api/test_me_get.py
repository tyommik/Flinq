from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


async def test_get_me_unauthorized_when_no_session() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/me")
        assert r.status_code == 401


async def test_get_me_returns_user_data_after_register() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/auth/register",
            json={
                "display_name": "Me",
                "email": "me-get@example.com",
                "password": "abcdefghij",
            },
        )
        assert r.status_code == 201
        user_id = r.json()["id"]

        r = await c.get("/me")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == user_id
        assert body["email"] == "me-get@example.com"
        assert body["role"] == "learner"
        assert body["display_name"] == "Me"
        assert body["ui_language_code"] == "en"  # default
        assert body["learning_languages"] == []  # before onboarding
        assert body["last_learning_language_code"] is None
        assert body["needs_onboarding"] is True
        assert body["onboarded_at"] is None


async def test_get_me_after_logout_returns_401() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post(
            "/auth/register",
            json={
                "display_name": "X",
                "email": "me-logout@example.com",
                "password": "abcdefghij",
            },
        )
        csrf = c.cookies.get("flinq_csrf")
        assert csrf
        await c.post("/auth/logout", headers={"X-CSRF-Token": csrf})

        r = await c.get("/me")
        assert r.status_code == 401
