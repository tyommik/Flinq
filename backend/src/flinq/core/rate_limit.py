"""Redis-backed rate limiter for auth endpoints (ADR-0008)."""

from __future__ import annotations

from redis.asyncio import Redis


class RateLimiter:
    def __init__(self, redis: Redis, *, max_attempts: int, window_seconds: int) -> None:
        self.redis = redis
        self.max = max_attempts
        self.window = window_seconds

    async def check_and_increment(self, key: str) -> bool:
        """Return True if under limit (and increment), False if over."""
        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, self.window)
        return current <= self.max

    async def reset(self, key: str) -> None:
        await self.redis.delete(key)

    async def get_retry_after(self, key: str) -> int:
        ttl = await self.redis.ttl(key)
        return max(ttl, 0)
