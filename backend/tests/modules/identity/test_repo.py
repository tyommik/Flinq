from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.identity.repo import SessionRepo, UserRepo


async def test_create_user_with_profile_and_settings(db_session: AsyncSession) -> None:
    repo = UserRepo(db_session)
    user = await repo.create(email="alice@example.com", password_hash="hash", display_name="Alice")
    assert user.id is not None
    assert user.email == "alice@example.com"
    assert user.role == "learner"
    assert user.profile.display_name == "Alice"
    assert user.settings is not None


async def test_get_by_email_case_insensitive(db_session: AsyncSession) -> None:
    repo = UserRepo(db_session)
    await repo.create(email="bob@example.com", password_hash="h", display_name="Bob")
    user = await repo.get_by_email("BOB@example.com")
    assert user is not None and user.email == "bob@example.com"


async def test_email_uniqueness(db_session: AsyncSession) -> None:
    repo = UserRepo(db_session)
    await repo.create(email="x@x.com", password_hash="h", display_name="X")
    with pytest.raises(IntegrityError):
        await repo.create(email="x@x.com", password_hash="h", display_name="X2")


async def test_session_create_and_lookup(db_session: AsyncSession) -> None:
    user_repo = UserRepo(db_session)
    user = await user_repo.create(email="s@s.com", password_hash="h", display_name="S")
    sess_repo = SessionRepo(db_session)
    await sess_repo.create(
        token="abc",
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=30),
        user_agent="test",
        ip_hash="hashed-ip",
    )
    found = await sess_repo.get_active("abc")
    assert found is not None and found.user_id == user.id


async def test_session_expired_returns_none(db_session: AsyncSession) -> None:
    user_repo = UserRepo(db_session)
    user = await user_repo.create(email="exp@x.com", password_hash="h", display_name="E")
    sess_repo = SessionRepo(db_session)
    await sess_repo.create(
        token="expired",
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert await sess_repo.get_active("expired") is None
