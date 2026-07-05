"""ai_requests schema: metadata-only audit row round-trip, user FK cascade (spec Decision 5)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.ai_translation.models import AIRequest
from flinq.modules.identity.repo import UserRepo


@pytest.fixture(autouse=True)
async def _clean_audit(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    """The round-trip test flushes-but-never-deletes an AIRequest row; session_scope
    commits it on clean fixture exit, leaking a permanent row (see test_service.py's
    own _clean_audit for the sibling pattern)."""
    yield

    await db_session.execute(delete(AIRequest))
    await db_session.commit()


async def _make_user(session: AsyncSession) -> uuid.UUID:
    user = await UserRepo(session).create(
        email=f"ai-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name="T",
        role="learner",
    )
    await session.flush()
    return user.id


async def test_audit_row_round_trip(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    row = AIRequest(
        request_id=uuid.uuid4(),
        user_id=user_id,
        lesson_id=None,
        provider="api.openai.com",
        model="gpt-4o-mini",
        prompt_hash="a" * 64,
        selected_text_hash="b" * 64,
        input_tokens=42,
        output_tokens=7,
        latency_ms=840,
        success=True,
        error_code=None,
    )
    db_session.add(row)
    await db_session.flush()
    loaded = await db_session.get(AIRequest, row.id)
    assert loaded is not None
    assert loaded.success is True
    assert loaded.created_at is not None
    assert loaded.item_kind is None and loaded.item_id is None


async def test_user_delete_cascades_audit(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    db_session.add(
        AIRequest(
            request_id=uuid.uuid4(),
            user_id=user_id,
            provider="p",
            model="m",
            prompt_hash="a" * 64,
            selected_text_hash="b" * 64,
            latency_ms=1,
            success=False,
            error_code="provider_unavailable",
        )
    )
    await db_session.flush()
    from flinq.modules.identity.models import User

    user = await db_session.get(User, user_id)
    assert user is not None
    db_session.expire(user, ["profile", "settings"])  # unload one-to-ones: defer cascade to the DB
    await db_session.delete(user)
    await db_session.flush()
    db_session.expire_all()  # DB-level cascade; identity map is stale (see FLQ-2 pattern)
    count = await db_session.scalar(
        select(func.count()).select_from(AIRequest).where(AIRequest.user_id == user_id)
    )
    assert count == 0
