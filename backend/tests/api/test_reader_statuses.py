"""GET /api/lessons/{id}/token-statuses — per-lesson token status map (FLQ-4.3)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.main import create_app
from flinq.modules.identity.repo import UserRepo
from flinq.modules.lesson_library import service
from flinq.modules.vocabulary.models import TokenItem

# Two paragraphs, genuine Portuguese diacritics — must survive byte-for-byte.
# Copied from tests/api/test_reader_content.py::_seed_ready_lesson's fixture text
# (Task 5 will extract a shared helper).
TEXT = "O edifício antigo fica na praça. Eu gosto dele.\n\nSegundo parágrafo aqui."


@pytest.fixture(autouse=True)
async def _clean(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    yield
    await db_session.execute(delete(TokenItem))
    await db_session.commit()


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

    Mirrors tests/api/test_reader_content.py::_seed_ready_lesson.
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


async def test_token_statuses_filters_to_lesson_words_and_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        email = "reader-statuses@example.com"
        csrf = await _register_and_onboard(c, email, lang="pt")
        lesson_id = await _seed_ready_lesson(c, csrf, monkeypatch)

        async with session_scope() as s:
            user = await UserRepo(s).get_by_email(email)
            assert user is not None
            user_id = user.id

            s.add(
                TokenItem(
                    user_id=user_id,
                    language_code="pt",
                    token_text="edifício",  # in-lesson word
                    status="known",
                    confidence=None,
                )
            )
            s.add(
                TokenItem(
                    user_id=user_id,
                    language_code="pt",
                    token_text="praça",  # in-lesson word
                    status="tracked",
                    confidence=2,
                )
            )
            s.add(
                TokenItem(
                    user_id=user_id,
                    language_code="pt",
                    token_text="zzz",  # not in the lesson
                    status="known",
                    confidence=None,
                )
            )
            s.add(
                TokenItem(
                    user_id=user_id,
                    language_code="en",  # in-lesson word, different language
                    token_text="antigo",
                    status="known",
                    confidence=None,
                )
            )

        r = await c.get(f"/api/lessons/{lesson_id}/token-statuses")
        assert r.status_code == 200
        body = r.json()

        statuses = body["statuses"]
        assert set(statuses.keys()) == {"edifício", "praça"}
        assert statuses["edifício"]["s"] == "known"
        assert statuses["edifício"].get("c") is None
        assert statuses["praça"] == {"s": "tracked", "c": 2}


async def test_token_statuses_empty_map_for_fresh_lesson(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "reader-statuses-empty@example.com", lang="pt")
        lesson_id = await _seed_ready_lesson(c, csrf, monkeypatch)

        r = await c.get(f"/api/lessons/{lesson_id}/token-statuses")
        assert r.status_code == 200
        assert r.json() == {"statuses": {}}


async def test_token_statuses_requires_auth() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/api/lessons/{uuid.uuid4()}/token-statuses")
        assert r.status_code == 401
