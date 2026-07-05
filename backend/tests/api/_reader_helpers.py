"""Shared fixtures for reader-state API tests (FLQ-4 Tasks 2-5).

Extracted from the copy-pasted helpers in test_reader_content.py,
test_reader_statuses.py, and test_reader_positions.py so new reader tests
(and those three) share one implementation.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from flinq.core.db import session_scope
from flinq.modules.lesson_library import service

# Two paragraphs, genuine Portuguese diacritics — must survive byte-for-byte.
TEXT = "O edifício antigo fica na praça. Eu gosto dele.\n\nSegundo parágrafo aqui."


async def register_and_onboard(c: AsyncClient, email: str, lang: str = "pt") -> str:
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


async def seed_ready_lesson(
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

    Mirrors tests/api/test_lessons.py::test_create_and_list_lesson: in env=test the
    InMemoryBroker would otherwise process the lesson before we can drive it, so the
    enqueue call is stubbed to a no-op and `process_lesson_import` is run explicitly.
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
