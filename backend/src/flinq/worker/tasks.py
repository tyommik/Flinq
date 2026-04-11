"""Task registry. Import this module to register all Taskiq tasks."""

from __future__ import annotations

from loguru import logger

from flinq.worker.broker import broker


@broker.task
async def ping() -> str:
    """Smoke-test task used by tests and health scripts."""
    logger.info("ping task executed")
    return "pong"