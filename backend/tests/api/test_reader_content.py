"""GET /api/lessons/{id}/content — tokenized lesson content (spec API-1)."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.main import create_app
from flinq.modules.lesson_library.models import Lesson, LessonTokenOccurrence
from tests.api._reader_helpers import TEXT
from tests.api._reader_helpers import register_and_onboard as _register_and_onboard
from tests.api._reader_helpers import seed_ready_lesson as _seed_ready_lesson


async def test_content_shape_and_reconstruction(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "reader-content@example.com", lang="pt")
        lesson_id = await _seed_ready_lesson(c, csrf, monkeypatch)

        r = await c.get(f"/api/lessons/{lesson_id}/content")
        assert r.status_code == 200
        body = r.json()

        assert body["lesson_id"] == str(lesson_id)
        assert body["language_code"] == "pt"
        assert len(body["paragraphs"]) == 2
        assert len(body["paragraphs"][0]["sentences"]) == 2
        assert len(body["paragraphs"][1]["sentences"]) == 1
        assert body["word_count"] == 12  # O, edifício, antigo, fica, na, praça,
        # Eu, gosto, dele, Segundo, parágrafo, aqui — pinned from the first GREEN run.

        # Cross-check word_count against the persisted facts directly.
        lesson = await db_session.get(Lesson, lesson_id)
        assert lesson is not None
        assert lesson.word_count == 12
        db_word_count = (
            await db_session.scalars(
                select(LessonTokenOccurrence).where(
                    LessonTokenOccurrence.lesson_id == lesson_id,
                    LessonTokenOccurrence.is_word_like.is_(True),
                )
            )
        ).all()
        assert len(db_word_count) == 12

        prev_sentence_ordinal = -1
        prev_token_ordinal = -1
        for para in body["paragraphs"]:
            for sent in para["sentences"]:
                assert sent["index"] > prev_sentence_ordinal
                prev_sentence_ordinal = sent["index"]

                pieces: list[str] = []
                for tok in sent["tokens"]:
                    if "t" in tok:
                        assert tok["i"] > prev_token_ordinal
                        prev_token_ordinal = tok["i"]
                        pieces.append(tok["t"])
                    elif "ws" in tok:
                        pieces.append(tok["ws"])
                    else:
                        pieces.append(tok["p"])
                assert "".join(pieces) == sent["text"]

        # Diacritics must survive byte-for-byte in both the sentence text and tokens.
        all_text = "".join(
            sent["text"] for para in body["paragraphs"] for sent in para["sentences"]
        )
        assert "edifício" in all_text
        assert "parágrafo" in all_text


async def test_content_requires_auth() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/api/lessons/{uuid.uuid4()}/content")
        assert r.status_code == 401


async def test_content_foreign_private_403_unknown_404(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = ASGITransport(app=create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as owner_client:
        owner_csrf = await _register_and_onboard(owner_client, "reader-owner@example.com")
        lesson_id = await _seed_ready_lesson(
            owner_client, owner_csrf, monkeypatch, visibility="private"
        )

    lesson = await db_session.get(Lesson, lesson_id)
    assert lesson is not None
    assert lesson.visibility == "private"

    async with AsyncClient(transport=transport, base_url="http://test") as other_client:
        await _register_and_onboard(other_client, "reader-other@example.com")

        r = await other_client.get(f"/api/lessons/{lesson_id}/content")
        assert r.status_code == 403

        r = await other_client.get(f"/api/lessons/{uuid.uuid4()}/content")
        assert r.status_code == 404


async def test_content_processing_lesson_409(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _noop(lesson_id: object, job_id: object) -> None:
        return None

    monkeypatch.setattr("flinq.api.lessons.enqueue_lesson_import", _noop)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "reader-processing@example.com")
        r = await c.post(
            "/api/lessons",
            json={
                "title": "Still cooking",
                "language_code": "pt",
                "raw_text": TEXT,
                "visibility": "private",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 202
        lesson_id = r.json()["id"]

        lesson = await db_session.get(Lesson, uuid.UUID(lesson_id))
        assert lesson is not None
        assert lesson.status == "processing"

        r = await c.get(f"/api/lessons/{lesson_id}/content")
        assert r.status_code == 409
        assert r.json() == {"detail": "lesson_not_ready"}
