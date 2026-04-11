"""Pytest fixtures shared across backend tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

# Ensure settings are loaded in "test" mode before anything else is imported.
os.environ.setdefault("FLINQ_ENV", "test")
os.environ.setdefault("FLINQ_SECRET_KEY", "test-secret-key-for-pytest")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client bound to the FastAPI app via ASGI transport (no network)."""
    from flinq.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac