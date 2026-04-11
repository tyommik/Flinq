"""Smoke test: GET /health returns 200 OK with version info."""

from __future__ import annotations

from httpx import AsyncClient

from flinq import __version__


async def test_health_endpoint_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__