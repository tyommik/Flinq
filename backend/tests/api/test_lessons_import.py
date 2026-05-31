"""POST returns 202 + processing and enqueues; GET polls status (AC#3)."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


async def _register_and_onboard(c: AsyncClient, email: str, lang: str = "pt") -> str:
    r = await c.post(
        "/auth/register",
        json={"display_name": "T", "email": email, "password": "abcdefghij"},
    )
    assert r.status_code == 201
    csrf = c.cookies.get("flinq_csrf")
    assert csrf
    await c.post(
        "/me/onboarding",
        json={"ui_language": "en", "learning_languages": [lang], "translation_language": "en"},
        headers={"X-CSRF-Token": csrf},
    )
    return csrf


async def test_post_returns_202_processing_and_enqueues(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def _spy(lesson_id, job_id) -> None:
        calls.append((str(lesson_id), str(job_id)))

    monkeypatch.setattr("flinq.api.lessons.enqueue_lesson_import", _spy)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "import-202@example.com")
        r = await c.post(
            "/api/lessons",
            json={
                "title": "Olá",
                "language_code": "pt",
                "raw_text": "Olá mundo. Tudo bem?",
                "visibility": "private",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "processing"
        assert "id" in body
        assert len(calls) == 1
        assert calls[0][0] == body["id"]
        assert calls[0][1]

        r2 = await c.get(f"/api/lessons/{body['id']}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "processing"


async def test_enqueue_failure_marks_failed_and_returns_503(monkeypatch) -> None:
    """If the queue is down, the lesson must not be stranded in processing (review #1)."""

    async def _boom(lesson_id, job_id) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr("flinq.api.lessons.enqueue_lesson_import", _boom)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "import-enqueue-fail@example.com")
        r = await c.post(
            "/api/lessons",
            json={
                "title": "Stuck?",
                "language_code": "pt",
                "raw_text": "Olá mundo.",
                "visibility": "private",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 503

        r2 = await c.get("/api/lessons?lang=pt")
        assert r2.status_code == 200
        statuses = {item["title"]: item["status"] for item in r2.json()["items"]}
        assert statuses.get("Stuck?") == "failed"


async def test_get_unknown_lesson_returns_404(monkeypatch) -> None:
    async def _spy(lesson_id, job_id) -> None:
        return None

    monkeypatch.setattr("flinq.api.lessons.enqueue_lesson_import", _spy)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register_and_onboard(c, "import-404@example.com")
        r = await c.get("/api/lessons/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404


async def test_get_requires_auth() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/lessons/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 401
