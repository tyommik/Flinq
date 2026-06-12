"""Async SQLAlchemy engine and session factory.

Single `Base` for ORM models will be introduced per-module under `flinq.modules.*`.
This file only owns the connection lifecycle.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

if TYPE_CHECKING:
    from flinq.core.config import Settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the initialized async engine (raises if not initialized)."""
    if _engine is None:
        raise RuntimeError("Engine not initialized; call init_engine() first.")
    return _engine


def init_engine(settings: Settings) -> AsyncEngine:
    """Create the engine. Idempotent — safe to call multiple times."""
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.is_dev and settings.log_level == "DEBUG",
            pool_pre_ping=True,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


async def dispose_engine() -> None:
    """Dispose the engine. Call on application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession]:
    """Async context manager yielding a session with automatic commit/rollback."""
    if _session_factory is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an async session."""
    async with session_scope() as session:
        yield session
