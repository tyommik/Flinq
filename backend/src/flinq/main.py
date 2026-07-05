"""FastAPI application factory.

Used by both uvicorn (`flinq.main:app`) and the `flinq serve` CLI entry point.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from flinq import __version__
from flinq.api.ai import router as ai_router
from flinq.api.auth import router as auth_router
from flinq.api.dictionary import router as dictionary_router
from flinq.api.health import router as health_router
from flinq.api.lessons import router as lessons_router
from flinq.api.me import router as me_router
from flinq.api.reader import router as reader_router
from flinq.core.config import get_settings
from flinq.core.db import dispose_engine, init_engine
from flinq.core.logging import configure_logging
from flinq.modules.identity.middleware import CSRFMiddleware, SessionMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: initialise engine, yield, then dispose on shutdown."""
    settings = get_settings()
    configure_logging(settings)
    init_engine(settings)
    logger.info("Flinq API starting (version={}, env={})", __version__, settings.env)
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("Flinq API stopped")


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Flinq API",
        version=__version__,
        lifespan=lifespan,
    )

    # Starlette stacks middleware in reverse add order: last added = outermost (runs first).
    # Execution order wanted: Session (sets state) → CSRF (reads cookies) → handler → GZip.
    # GZip must be innermost (closest to the handler) so it compresses responses
    # before they pass back up through CSRF/Session — it is added FIRST.
    # Session must be outermost, so it is added LAST.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(SessionMiddleware)  # outer — runs first per request

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(lessons_router)
    app.include_router(reader_router)
    app.include_router(dictionary_router)
    app.include_router(ai_router)

    # Serve frontend static assets in production (see architecture §5.3).
    if settings.static_dir is not None and settings.static_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(settings.static_dir), html=True),
            name="frontend",
        )

    return app


app = create_app()
