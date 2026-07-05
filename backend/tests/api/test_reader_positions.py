"""PUT /api/reader/positions + lesson GET reader_position extension (FLQ-4 Task 4)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.main import create_app
from flinq.modules.lesson_library import service
from flinq.modules.reader_state.models import ReaderPosition

# Genuine Portuguese, diacritics included — mirrors test_reader_content.py fixture style.
TEXT = "O edifício antigo fica na praça. Eu gosto dele.\n\nSegundo parágrafo aqui."


@pytest.fixture(autouse=True)
async def _cleanup_reader_positions() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction] — autouse fixture
    yield
    async with session_scope() as s:
        await s.execute(delete(ReaderPosition))
        await s.commit()


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


async def _seed_ready_lesson(
    c: AsyncClient,
    csrf: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = TEXT,
    language_code: str = "pt",
    visibility: str = "private",
    title: str = "Reader fixture",
) -> uuid.UUID:
    """POST a lesson (enqueue stubbed inline) then run the import pipeline directly.

    Local copy of the helper in test_reader_content.py (Task 5 extracts it to a
    shared conftest fixture).
    """

    async def _noop(lesson_id: object, job_id: object) -> None:
        return None

    monkeypatch.setattr("flinq.api.lessons.enqueue_lesson_import", _noop)

    r = await c.post(
        "/api/lessons",
        json={
            "title": title,
            "language_code": language_code,
            "raw_text": text,
            "visibility": visibility,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 202
    lesson_id = uuid.UUID(r.json()["id"])

    async with session_scope() as s:
        await service.process_lesson_import(s, lesson_id)

    return lesson_id


async def test_put_position_then_get_lesson_reflects_it(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "reader-pos-1@example.com")
        lesson_id = await _seed_ready_lesson(c, csrf, monkeypatch)

        r = await c.get(f"/api/lessons/{lesson_id}/content")
        assert r.status_code == 200
        seg_id = r.json()["paragraphs"][0]["sentences"][0]["seg_id"]

        r = await c.put(
            "/api/reader/positions",
            json={
                "lesson_id": str(lesson_id),
                "view_mode": "sentence",
                "current_segment_id": seg_id,
                "current_token_ordinal": 3,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 204

        r = await c.get(f"/api/lessons/{lesson_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["reader_position"] == {
            "view_mode": "sentence",
            "current_segment_id": seg_id,
            "current_token_ordinal": 3,
        }


async def test_second_put_updates_same_row_no_duplicate(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "reader-pos-2@example.com")
        lesson_id = await _seed_ready_lesson(c, csrf, monkeypatch)

        r = await c.get(f"/api/lessons/{lesson_id}/content")
        sentences = [sent for para in r.json()["paragraphs"] for sent in para["sentences"]]
        seg_id_1 = sentences[0]["seg_id"]
        seg_id_2 = sentences[1]["seg_id"]

        r = await c.put(
            "/api/reader/positions",
            json={
                "lesson_id": str(lesson_id),
                "view_mode": "page",
                "current_segment_id": seg_id_1,
                "current_token_ordinal": 0,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 204

        r = await c.put(
            "/api/reader/positions",
            json={
                "lesson_id": str(lesson_id),
                "view_mode": "sentence",
                "current_segment_id": seg_id_2,
                "current_token_ordinal": 5,
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 204

        rows = (
            await db_session.scalars(
                select(ReaderPosition).where(ReaderPosition.lesson_id == lesson_id)
            )
        ).all()
        assert len(rows) == 1

        r = await c.get(f"/api/lessons/{lesson_id}")
        body = r.json()
        assert body["reader_position"] == {
            "view_mode": "sentence",
            "current_segment_id": seg_id_2,
            "current_token_ordinal": 5,
        }


async def test_put_position_foreign_private_lesson_403(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = ASGITransport(app=create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as owner_client:
        owner_csrf = await _register_and_onboard(owner_client, "reader-pos-owner@example.com")
        lesson_id = await _seed_ready_lesson(
            owner_client, owner_csrf, monkeypatch, visibility="private"
        )

    async with AsyncClient(transport=transport, base_url="http://test") as other_client:
        other_csrf = await _register_and_onboard(other_client, "reader-pos-other@example.com")

        r = await other_client.put(
            "/api/reader/positions",
            json={
                "lesson_id": str(lesson_id),
                "view_mode": "page",
                "current_segment_id": None,
                "current_token_ordinal": None,
            },
            headers={"X-CSRF-Token": other_csrf},
        )
        assert r.status_code == 403


async def test_put_position_requires_auth() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Bare PUT with no session/CSRF cookie at all: the CSRF middleware rejects
        # the request before the auth dependency ever runs — same platform
        # behavior as POST /api/lessons (see test_lessons.py::test_create_requires_auth).
        r = await c.put(
            "/api/reader/positions",
            json={
                "lesson_id": str(uuid.uuid4()),
                "view_mode": "page",
                "current_segment_id": None,
                "current_token_ordinal": None,
            },
        )
        assert r.status_code == 403


async def test_get_lesson_without_position_returns_null(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "reader-pos-3@example.com")
        lesson_id = await _seed_ready_lesson(c, csrf, monkeypatch)

        r = await c.get(f"/api/lessons/{lesson_id}")
        assert r.status_code == 200
        assert r.json()["reader_position"] is None
