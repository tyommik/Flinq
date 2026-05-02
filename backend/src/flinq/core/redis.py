"""Async Redis client (used for rate limiting and AI cache)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from redis.asyncio import Redis

from flinq.core.config import get_settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    """Module-level singleton (lazy)."""
    global _client  # noqa: PLW0603,RUF100
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def get_redis() -> AsyncIterator[Redis]:
    """FastAPI dependency."""
    yield get_redis_client()


async def dispose_redis() -> None:
    global _client  # noqa: PLW0603,RUF100
    if _client is not None:
        await _client.aclose()
        _client = None
