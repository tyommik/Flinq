import redis.asyncio as aioredis

from flinq.core.rate_limit import RateLimiter


async def test_first_n_requests_allowed(redis_client: aioredis.Redis) -> None:
    rl = RateLimiter(redis_client, max_attempts=5, window_seconds=900)
    for _ in range(5):
        assert await rl.check_and_increment("login:1.2.3.4:user@x") is True


async def test_n_plus_one_blocked(redis_client: aioredis.Redis) -> None:
    rl = RateLimiter(redis_client, max_attempts=3, window_seconds=900)
    for _ in range(3):
        await rl.check_and_increment("login:k1")
    assert await rl.check_and_increment("login:k1") is False


async def test_reset(redis_client: aioredis.Redis) -> None:
    rl = RateLimiter(redis_client, max_attempts=3, window_seconds=900)
    await rl.check_and_increment("login:k2")
    await rl.reset("login:k2")
    for _ in range(3):
        assert await rl.check_and_increment("login:k2") is True


async def test_get_retry_after_returns_window_after_first_call(
    redis_client: aioredis.Redis,
) -> None:
    rl = RateLimiter(redis_client, max_attempts=3, window_seconds=120)
    await rl.check_and_increment("login:k3")
    ttl = await rl.get_retry_after("login:k3")
    assert 0 < ttl <= 120
