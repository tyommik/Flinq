"""Pytest fixtures shared across backend tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from flinq.core.config import get_settings
from flinq.core.db import dispose_engine, init_engine, session_scope

# Ensure settings are loaded in "test" mode before anything else is imported.
os.environ.setdefault("FLINQ_ENV", "test")
os.environ.setdefault("FLINQ_SECRET_KEY", "test-secret-key-for-pytest")


@pytest.fixture(scope="session")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="session")
def _pg_container() -> Iterator[PostgresContainer]:  # pyright: ignore[reportUnusedFunction] — fixture, injected by name
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg


@pytest.fixture(scope="session", autouse=True)
def _db_setup(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    _pg_container: PostgresContainer, monkeypatch_session: pytest.MonkeyPatch
) -> None:
    url = _pg_container.get_connection_url()  # already asyncpg-formatted
    monkeypatch_session.setenv("FLINQ_DATABASE_URL", url)
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _redis_setup(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    _redis_container: RedisContainer, monkeypatch_session: pytest.MonkeyPatch
) -> None:
    host = _redis_container.get_container_host_ip()
    port = int(_redis_container.get_exposed_port(6379))
    monkeypatch_session.setenv("FLINQ_REDIS_URL", f"redis://{host}:{port}/0")
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
async def _init_schema(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    _db_setup: None, _redis_setup: None
) -> AsyncIterator[None]:
    from flinq.core.db import Base

    # Side-effect imports: register ORM models on Base.metadata before create_all.
    from flinq.modules.ai_translation import (
        models as _ai_models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    )
    from flinq.modules.dictionary import (
        models as _dictionary_models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    )
    from flinq.modules.identity import (
        models as _identity_models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    )
    from flinq.modules.lesson_library import (
        models as _lesson_models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    )
    from flinq.modules.reader_state import (
        models as _reader_state_models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    )
    from flinq.modules.vocabulary import (
        models as _vocabulary_models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    )

    settings = get_settings()
    engine = init_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()
    from flinq.core.redis import dispose_redis

    await dispose_redis()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    try:
        async with session_scope() as s:
            yield s
    except PendingRollbackError:
        # A test intentionally triggered a DB exception (e.g. uniqueness test).
        # session_scope already rolled back; swallow the teardown error cleanly.
        pass


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client bound to the FastAPI app via ASGI transport (no network)."""
    from flinq.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(scope="session")
def _redis_container() -> Iterator[RedisContainer]:  # pyright: ignore[reportUnusedFunction] — fixture, injected by name
    with RedisContainer("redis:7-alpine") as r:
        yield r


@pytest.fixture
async def redis_client(_redis_container: RedisContainer) -> AsyncIterator[aioredis.Redis]:
    host = _redis_container.get_container_host_ip()
    port = int(_redis_container.get_exposed_port(6379))
    client = aioredis.Redis(host=host, port=port, decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()
