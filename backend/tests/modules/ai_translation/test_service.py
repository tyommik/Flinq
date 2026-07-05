"""translate_hints orchestration: audit rows, kill-switch, privacy (spec Decision 4)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.config import get_settings
from flinq.modules.ai_translation import service
from flinq.modules.ai_translation.models import AIRequest
from flinq.modules.ai_translation.provider import LLMCompletion, ProviderUnavailable
from flinq.modules.identity.repo import UserRepo

SURFACE = "later"
CONTEXT = "See you later!"


class FakeProvider:
    def __init__(
        self,
        *,
        text: str = "позже\nпотом",  # noqa: RUF001 -- Cyrillic sample text is intentional
        error: Exception | None = None,
    ) -> None:
        self.text = text
        self.error = error
        self.calls = 0

    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMCompletion(text=self.text, input_tokens=42, output_tokens=7)


@pytest.fixture(autouse=True, scope="module")
async def _reset_audit_before_module() -> None:  # pyright: ignore[reportUnusedFunction] — autouse fixture
    """Other modules' tests share this Postgres instance with no per-test rollback
    (see tests/modules/ai_translation/test_models_schema.py::test_audit_row_round_trip,
    which flushes-but-never-deletes an AIRequest row). Clear any such leakage before
    this file's row-count assertions run; `_clean_audit` below still owns per-test
    cleanup for rows this file creates.
    """
    from sqlalchemy import delete

    from flinq.core.db import session_scope

    async with session_scope() as session:
        await session.execute(delete(AIRequest))


@pytest.fixture(autouse=True)
def _llm_enabled(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", True)


@pytest.fixture(autouse=True)
async def _clean_audit(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    yield

    from sqlalchemy import delete

    await db_session.execute(delete(AIRequest))
    await db_session.commit()


async def _user(db_session: AsyncSession) -> uuid.UUID:
    user = await UserRepo(db_session).create(
        email=f"svc-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name="T",
        role="learner",
    )
    await db_session.flush()
    return user.id


async def _audit_rows(db_session: AsyncSession) -> list[AIRequest]:
    return list((await db_session.scalars(select(AIRequest))).all())


async def test_success_returns_hints_and_audits(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    result = await service.translate_hints(
        db_session,
        user_id=user_id,
        surface_text=SURFACE,
        context_text=CONTEXT,
        target_language_code="ru",
        provider=FakeProvider(),
    )
    assert result.hints == ["позже", "потом"]
    assert result.latency_ms >= 0
    [row] = await _audit_rows(db_session)
    assert row.success is True and row.error_code is None
    assert row.input_tokens == 42 and row.output_tokens == 7
    assert len(row.prompt_hash) == 64 and len(row.selected_text_hash) == 64


async def test_provider_failure_audits_and_reraises(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    with pytest.raises(ProviderUnavailable):
        await service.translate_hints(
            db_session,
            user_id=user_id,
            surface_text=SURFACE,
            context_text=CONTEXT,
            target_language_code="ru",
            provider=FakeProvider(error=ProviderUnavailable("down")),
        )
    [row] = await _audit_rows(db_session)
    assert row.success is False and row.error_code == "provider_unavailable"


async def test_empty_model_output_raises_and_audits(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    with pytest.raises(service.AIEmptyResponse):
        await service.translate_hints(
            db_session,
            user_id=user_id,
            surface_text=SURFACE,
            context_text=CONTEXT,
            target_language_code="ru",
            provider=FakeProvider(text="\n \n"),
        )
    [row] = await _audit_rows(db_session)
    assert row.success is False and row.error_code == "empty_response"


async def test_kill_switch_no_call_no_audit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", False)
    user_id = await _user(db_session)
    fake = FakeProvider()
    with pytest.raises(service.AIDisabled):
        await service.translate_hints(
            db_session,
            user_id=user_id,
            surface_text=SURFACE,
            context_text=CONTEXT,
            target_language_code="ru",
            provider=fake,
        )
    assert fake.calls == 0
    assert await _audit_rows(db_session) == []


async def test_privacy_audit_contains_no_raw_text(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    await service.translate_hints(
        db_session,
        user_id=user_id,
        surface_text=SURFACE,
        context_text=CONTEXT,
        target_language_code="ru",
        provider=FakeProvider(),
    )
    [row] = await _audit_rows(db_session)
    dump = " ".join(str(v) for v in vars(row).values())
    assert SURFACE not in dump
    assert CONTEXT not in dump
    assert "позже" not in dump


async def test_audit_failure_does_not_mask_result(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _user(db_session)
    original_commit = db_session.commit
    calls = {"n": 0}

    async def _failing_commit() -> None:
        if calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("db hiccup during audit")
        await original_commit()

    monkeypatch.setattr(db_session, "commit", _failing_commit)
    result = await service.translate_hints(
        db_session,
        user_id=user_id,
        surface_text=SURFACE,
        context_text=CONTEXT,
        target_language_code="ru",
        provider=FakeProvider(),
    )
    assert result.hints == ["позже", "потом"]  # result survived the audit failure
    # session must remain usable (no PendingRollbackError):
    assert await _audit_rows(db_session) == []
