from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flinq.core.db import Base

UserRole = Literal["learner", "admin"]


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(16), nullable=False, default="learner")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped[UserProfile] = relationship(back_populates="user", uselist=False)
    settings: Mapped[UserSettings] = relationship(back_populates="user", uselist=False)
    learning_languages: Mapped[list[UserLearningLanguage]] = relationship(back_populates="user")
    sessions: Mapped[list[UserSession]] = relationship(back_populates="user")

    __table_args__ = (CheckConstraint("role IN ('learner', 'admin')", name="users_role_check"),)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    native_language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    ui_language_code: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="profile")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    preferred_translation_language_code: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )
    last_learning_language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reader_view_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="page")
    audio_speed: Mapped[float] = mapped_column(nullable=False, default=1.0)
    daily_goal_minutes: Mapped[int] = mapped_column(nullable=False, default=15)
    daily_goal_reviews: Mapped[int] = mapped_column(nullable=False, default=20)

    user: Mapped[User] = relationship(back_populates="settings")


class UserLearningLanguage(Base):
    __tablename__ = "user_learning_languages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    language_code: Mapped[str] = mapped_column(String(8), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="learning_languages")

    __table_args__ = (
        UniqueConstraint("user_id", "language_code", name="user_learning_languages_unique"),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # base64url 256-bit
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")
