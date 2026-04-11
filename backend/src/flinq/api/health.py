"""Health check endpoint.

Returns 200 OK if the API process is alive. Does not verify database or Redis
connectivity — those have their own readiness checks (to be added later).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from flinq import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)