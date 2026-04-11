"""Loguru-based structured logging setup.

Call `configure_logging(settings)` once during application startup. After that
simply `from loguru import logger` and use it anywhere in the code base.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from flinq.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure loguru sinks based on settings.

    - dev: human-friendly colored output on stderr
    - prod/test: JSON-serialised records on stderr, ready for aggregation
    """
    logger.remove()

    if settings.is_dev:
        logger.add(
            sys.stderr,
            level=settings.log_level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
                "| <level>{level: <8}</level> "
                "| <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
                "| <level>{message}</level>"
            ),
            colorize=True,
            backtrace=True,
            diagnose=True,
        )
    else:
        logger.add(
            sys.stderr,
            level=settings.log_level,
            serialize=True,
            backtrace=False,
            diagnose=False,
        )

    logger.info("Logging configured (env={}, level={})", settings.env, settings.log_level)