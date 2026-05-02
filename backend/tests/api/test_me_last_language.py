from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


async def _register_and_onboard(c: AsyncClient, email: str, langs: list[str]) -> str:
    r = await c.post(
        "/auth/register",
        json={"display_name": "T", "email": email, "password": "abcdefghij"},
    )
    assert r.status_code == 201
    csrf = c.cookies.get("flinq_csrf")
    assert csrf
    await c.post(
        "/me/onboarding",
        json={
            "ui_language": "en",
            "learning_languages": langs,
            "translation_language": "en",
        },
        headers={"X-CSRF-Token": csrf},
    )
    return csrf


async def test_set_last_language_success() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "lang-ok@example.com", ["pt", "ru"])
        # First language is pt by default — switch to ru
        r = await c.patch(
            "/me/last-language",
            json={"language_code": "ru"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200

        r = await c.get("/me")
        assert r.json()["last_learning_language_code"] == "ru"


async def test_set_last_language_rejects_unknown_for_user() -> None:
    """User can only switch to languages they're studying."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "lang-bad@example.com", ["pt"])
        r = await c.patch(
            "/me/last-language",
            json={"language_code": "ru"},  # not in learning_languages
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 400


async def test_set_last_language_rejects_unsupported() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "lang-fr@example.com", ["pt"])
        r = await c.patch(
            "/me/last-language",
            json={"language_code": "fr"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 422
