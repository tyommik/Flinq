"""Taskiq broker setup.

Production uses a Redis broker. Tests swap in `InMemoryBroker` via environment.
"""

from __future__ import annotations

from taskiq import InMemoryBroker
from taskiq.abc.broker import AsyncBroker
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from flinq.core.config import get_settings

_settings = get_settings()


def _build_broker() -> AsyncBroker:
    if _settings.env == "test":
        return InMemoryBroker()
    return ListQueueBroker(url=_settings.redis_url).with_result_backend(
        RedisAsyncResultBackend(redis_url=_settings.redis_url)
    )


broker: AsyncBroker = _build_broker()