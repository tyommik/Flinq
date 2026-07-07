"""Taskiq broker setup.

Production uses a Redis broker. Tests swap in `InMemoryBroker` via environment.
"""

from __future__ import annotations

from taskiq import InMemoryBroker, TaskiqEvents, TaskiqState
from taskiq.abc.broker import AsyncBroker
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from flinq.core.config import get_settings
from flinq.core.db import dispose_engine, init_engine
from flinq.core.logging import configure_logging

_settings = get_settings()


def _build_broker() -> AsyncBroker:
    if _settings.env == "test":
        return InMemoryBroker()
    return ListQueueBroker(url=_settings.redis_url).with_result_backend(
        RedisAsyncResultBackend(redis_url=_settings.redis_url)
    )


broker: AsyncBroker = _build_broker()


# The worker process does not run the FastAPI lifespan, so it must initialise the
# database engine itself. Without this, any task using session_scope() fails with
# "Database engine not initialized". Mirrors flinq.main.lifespan. Tests use the
# InMemoryBroker and manage the engine via fixtures, so skip registration there.
if _settings.env != "test":

    @broker.on_event(TaskiqEvents.WORKER_STARTUP)
    async def _init_worker_engine(_state: TaskiqState) -> None:  # pyright: ignore[reportUnusedFunction]
        settings = get_settings()
        configure_logging(settings)
        init_engine(settings)

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def _dispose_worker_engine(_state: TaskiqState) -> None:  # pyright: ignore[reportUnusedFunction]
        await dispose_engine()
