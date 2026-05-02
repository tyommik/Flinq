"""End-to-end integration test for the full auth + onboarding flow.

Covers Tasks 9-14 endpoints in a single happy-path scenario:
register → /me → onboarding → /me → patch language → logout → /me.
"""

from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


async def test_full_auth_onboarding_flow() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 1. Register — auto-login
        r = await c.post(
            "/auth/register",
            json={
                "display_name": "Integration",
                "email": "integration@example.com",
                "password": "abcdefghij",
            },
        )
        assert r.status_code == 201
        assert r.json()["needs_onboarding"] is True
        csrf = c.cookies.get("flinq_csrf")
        assert csrf is not None
        assert c.cookies.get("flinq_session") is not None

        # 2. /me before onboarding
        r = await c.get("/me")
        assert r.status_code == 200
        me = r.json()
        assert me["needs_onboarding"] is True
        assert me["learning_languages"] == []
        assert me["last_learning_language_code"] is None

        # 3. Complete onboarding
        r = await c.post(
            "/me/onboarding",
            json={
                "ui_language": "ru",
                "learning_languages": ["pt", "en"],
                "translation_language": "ru",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200
        assert r.json()["redirect"] == "/learn/pt/library"

        # 4. /me after onboarding — needs_onboarding false, languages set
        r = await c.get("/me")
        me = r.json()
        assert me["needs_onboarding"] is False
        assert me["onboarded_at"] is not None
        assert me["ui_language_code"] == "ru"
        assert sorted(me["learning_languages"]) == ["en", "pt"]
        assert me["last_learning_language_code"] == "pt"

        # 5. Switch active language to en
        r = await c.patch(
            "/me/last-language",
            json={"language_code": "en"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200

        r = await c.get("/me")
        assert r.json()["last_learning_language_code"] == "en"

        # 6. Logout
        r = await c.post("/auth/logout", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200

        # 7. /me after logout — 401
        r = await c.get("/me")
        assert r.status_code == 401


async def test_login_existing_user_after_logout() -> None:
    """Re-login after logout works and reflects existing onboarding state."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Register and onboard
        await c.post(
            "/auth/register",
            json={
                "display_name": "Returning",
                "email": "returning@example.com",
                "password": "abcdefghij",
            },
        )
        csrf = c.cookies.get("flinq_csrf")
        assert csrf
        await c.post(
            "/me/onboarding",
            json={
                "ui_language": "en",
                "learning_languages": ["pt"],
                "translation_language": "en",
            },
            headers={"X-CSRF-Token": csrf},
        )
        await c.post("/auth/logout", headers={"X-CSRF-Token": csrf})

        # Fresh client (simulate new browser session)
    async with AsyncClient(transport=transport, base_url="http://test") as c2:
        r = await c2.post(
            "/auth/login",
            json={
                "email": "returning@example.com",
                "password": "abcdefghij",
                "remember_me": True,
            },
        )
        assert r.status_code == 200
        # User has already onboarded — needs_onboarding is False
        assert r.json()["needs_onboarding"] is False

        r = await c2.get("/me")
        me = r.json()
        assert me["learning_languages"] == ["pt"]
        assert me["last_learning_language_code"] == "pt"
