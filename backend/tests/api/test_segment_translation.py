"""POST /api/lessons/{lesson_id}/segments/{segment_id}/translation (spec API-6)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.config import get_settings
from flinq.main import create_app
from flinq.modules.ai_translation import service
from flinq.modules.ai_translation.models import AIRequest
from flinq.modules.ai_translation.provider import LLMCompletion
from flinq.modules.lesson_library.models import LessonSegment
from flinq.modules.reader_state.models import LessonSegmentTranslation
from tests.api._reader_helpers import register_and_onboard as _register_and_onboard
from tests.api._reader_helpers import seed_ready_lesson as _seed_ready_lesson


class _GoodProvider:
    def __init__(self, text: str = "Старое здание.") -> None:
        self.text = text
        self.calls = 0

    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        self.calls += 1
        return LLMCompletion(text=self.text, input_tokens=3, output_tokens=4)


@pytest.fixture(autouse=True)
async def _clean_up(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    yield

    await db_session.execute(delete(LessonSegmentTranslation))
    await db_session.execute(delete(AIRequest))
    await db_session.commit()


async def _first_segment_id(db_session: AsyncSession, lesson_id: uuid.UUID) -> uuid.UUID:
    segment = await db_session.scalar(
        select(LessonSegment)
        .where(LessonSegment.lesson_id == lesson_id)
        .order_by(LessonSegment.ordinal)
    )
    assert segment is not None
    return segment.id


async def test_first_call_translates_and_stores(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", True)
    fake = _GoodProvider()
    monkeypatch.setattr(service, "_default_provider", lambda: fake)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "seg-tr-first@example.com")
        lesson_id = await _seed_ready_lesson(c, csrf, monkeypatch)
        segment_id = await _first_segment_id(db_session, lesson_id)

        r = await c.post(
            f"/api/lessons/{lesson_id}/segments/{segment_id}/translation",
            json={"target_language_code": "ru"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["text"] == "Старое здание."
        assert body["stored"] is False
        assert body["source"] == "ai"
        assert body["model"]
        assert fake.calls == 1

        row = await db_session.scalar(
            select(LessonSegmentTranslation).where(
                LessonSegmentTranslation.segment_id == segment_id,
                LessonSegmentTranslation.target_language_code == "ru",
            )
        )
        assert row is not None
        assert row.translation_text == "Старое здание."


async def test_second_call_is_served_from_storage(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", True)
    fake = _GoodProvider()
    monkeypatch.setattr(service, "_default_provider", lambda: fake)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "seg-tr-second@example.com")
        lesson_id = await _seed_ready_lesson(c, csrf, monkeypatch)
        segment_id = await _first_segment_id(db_session, lesson_id)

        url = f"/api/lessons/{lesson_id}/segments/{segment_id}/translation"
        body = {"target_language_code": "ru"}
        r1 = await c.post(url, json=body, headers={"X-CSRF-Token": csrf})
        assert r1.status_code == 200
        assert r1.json()["stored"] is False

        r2 = await c.post(url, json=body, headers={"X-CSRF-Token": csrf})
        assert r2.status_code == 200
        assert r2.json()["stored"] is True
        assert r2.json()["text"] == "Старое здание."
        assert fake.calls == 1  # provider was not called again


async def test_ai_disabled_and_not_stored_returns_503(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", False)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "seg-tr-disabled@example.com")
        lesson_id = await _seed_ready_lesson(c, csrf, monkeypatch)
        segment_id = await _first_segment_id(db_session, lesson_id)

        r = await c.post(
            f"/api/lessons/{lesson_id}/segments/{segment_id}/translation",
            json={"target_language_code": "ru"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 503
        assert r.json()["detail"] == "ai_disabled"


async def test_ai_disabled_but_already_stored_returns_200(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _GoodProvider()

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "seg-tr-cached@example.com")
        lesson_id = await _seed_ready_lesson(c, csrf, monkeypatch)
        segment_id = await _first_segment_id(db_session, lesson_id)
        url = f"/api/lessons/{lesson_id}/segments/{segment_id}/translation"
        body = {"target_language_code": "ru"}

        monkeypatch.setattr(get_settings(), "llm_enabled", True)
        monkeypatch.setattr(service, "_default_provider", lambda: fake)
        r1 = await c.post(url, json=body, headers={"X-CSRF-Token": csrf})
        assert r1.status_code == 200
        assert r1.json()["stored"] is False

        monkeypatch.setattr(get_settings(), "llm_enabled", False)
        r2 = await c.post(url, json=body, headers={"X-CSRF-Token": csrf})
        assert r2.status_code == 200
        assert r2.json()["stored"] is True
        assert r2.json()["text"] == "Старое здание."
        assert fake.calls == 1  # no AI call needed once stored


async def test_segment_from_another_lesson_returns_404(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", True)
    monkeypatch.setattr(service, "_default_provider", lambda: _GoodProvider())

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "seg-tr-cross@example.com")
        lesson_a = await _seed_ready_lesson(c, csrf, monkeypatch, title="Lesson A")
        lesson_b = await _seed_ready_lesson(c, csrf, monkeypatch, title="Lesson B")
        segment_b = await _first_segment_id(db_session, lesson_b)

        r = await c.post(
            f"/api/lessons/{lesson_a}/segments/{segment_b}/translation",
            json={"target_language_code": "ru"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 404


async def test_unauthenticated_post_requires_csrf() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            f"/api/lessons/{uuid.uuid4()}/segments/{uuid.uuid4()}/translation",
            json={"target_language_code": "ru"},
        )
        assert r.status_code == 403
