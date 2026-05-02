from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


async def _register(c: AsyncClient, *, email: str) -> str:
    r = await c.post(
        "/auth/register",
        json={"display_name": "T", "email": email, "password": "abcdefghij"},
    )
    assert r.status_code == 201
    return c.cookies.get("flinq_csrf")  # type: ignore[return-value]


async def test_onboarding_persists_settings_and_redirect() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register(c, email="onb-ok@example.com")

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
        body = r.json()
        assert body["ok"] is True
        assert body["redirect"] == "/learn/pt/library"

        # Verify /me reflects the choices
        r = await c.get("/me")
        me = r.json()
        assert me["ui_language_code"] == "ru"
        assert sorted(me["learning_languages"]) == ["en", "pt"]
        assert me["last_learning_language_code"] == "pt"
        assert me["needs_onboarding"] is False
        assert me["onboarded_at"] is not None


async def test_onboarding_requires_auth() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/me/onboarding",
            json={
                "ui_language": "en",
                "learning_languages": ["pt"],
                "translation_language": "en",
            },
        )
        # No CSRF token → 403 (CSRFMiddleware runs before auth check)
        assert r.status_code == 403


async def test_onboarding_validates_language_codes() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register(c, email="onb-validate@example.com")

        r = await c.post(
            "/me/onboarding",
            json={
                "ui_language": "fr",  # not supported
                "learning_languages": ["pt"],
                "translation_language": "ru",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 422


async def test_onboarding_idempotent_reapply() -> None:
    """Re-submitting onboarding overwrites settings; languages dedup."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register(c, email="onb-rerun@example.com")

        # First submission
        await c.post(
            "/me/onboarding",
            json={
                "ui_language": "en",
                "learning_languages": ["pt"],
                "translation_language": "en",
            },
            headers={"X-CSRF-Token": csrf},
        )
        # Second submission with overlap and a new language
        r = await c.post(
            "/me/onboarding",
            json={
                "ui_language": "ru",
                "learning_languages": ["pt", "ru"],  # pt already exists
                "translation_language": "ru",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200
        assert r.json()["redirect"] == "/learn/pt/library"

        # Verify no duplicate pt rows
        r = await c.get("/me")
        me = r.json()
        assert sorted(me["learning_languages"]) == ["pt", "ru"]
        assert me["ui_language_code"] == "ru"
