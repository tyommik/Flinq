"""Task registry. Import this module to register all Taskiq tasks."""

from __future__ import annotations

from loguru import logger
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from flinq.core.db import session_scope
from flinq.modules.identity.repo import SessionRepo
from flinq.worker.broker import broker


@broker.task
async def ping() -> str:
    """Smoke-test task used by tests and health scripts."""
    logger.info("ping task executed")
    return "pong"


@broker.task(schedule=[{"cron": "0 3 * * *"}])  # daily at 03:00
async def cleanup_expired_sessions() -> int:
    """Delete user_sessions rows whose expires_at is in the past (ADR-0008)."""
    async with session_scope() as s:
        deleted = await SessionRepo(s).cleanup_expired()
        if deleted:
            logger.info("cleanup_expired_sessions: removed {} sessions", deleted)
        return deleted


scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
