from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.identity.models import (
    User,
    UserProfile,
    UserSession,
    UserSettings,
)


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        role: str = "learner",
    ) -> User:
        user = User(
            email=email.lower().strip(),
            password_hash=password_hash,
            role=role,
        )
        user.profile = UserProfile(display_name=display_name)
        user.settings = UserSettings()
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower().strip())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def mark_onboarded(self, user_id: uuid.UUID, when: datetime) -> None:
        await self.session.execute(update(User).where(User.id == user_id).values(onboarded_at=when))

    async def hard_delete(self, user_id: uuid.UUID) -> None:
        user = await self.session.get(User, user_id)
        if user is not None:
            await self.session.delete(user)


class SessionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        token: str,
        user_id: uuid.UUID,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_hash: str | None = None,
    ) -> UserSession:
        sess = UserSession(
            id=token,
            user_id=user_id,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_hash=ip_hash,
        )
        self.session.add(sess)
        await self.session.flush()
        return sess

    async def get_active(self, token: str) -> UserSession | None:
        stmt = select(UserSession).where(
            UserSession.id == token,
            UserSession.expires_at > func.now(),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def touch(self, token: str, *, new_expires_at: datetime) -> None:
        await self.session.execute(
            update(UserSession)
            .where(UserSession.id == token)
            .values(last_seen_at=func.now(), expires_at=new_expires_at)
        )

    async def invalidate(self, token: str) -> None:
        await self.session.execute(
            update(UserSession).where(UserSession.id == token).values(expires_at=func.now())
        )

    async def cleanup_expired(self) -> int:
        result: CursorResult[tuple[()]] = await self.session.execute(  # type: ignore[assignment]
            delete(UserSession).where(UserSession.expires_at < func.now())
        )
        return result.rowcount or 0
