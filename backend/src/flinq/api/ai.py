"""AI contextual translation API (spec: FLQ-3)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.ai_translation import service
from flinq.modules.ai_translation.provider import ProviderRejected, ProviderUnavailable
from flinq.modules.ai_translation.schemas import HintOut, TranslateRequest, TranslateResponse

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _require_user(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user_id


@router.post("/translate", response_model=TranslateResponse)
async def translate(
    request: Request,
    body: TranslateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranslateResponse:
    user_id = _require_user(request)
    try:
        result = await service.translate_hints(
            session,
            user_id=user_id,
            surface_text=body.surface_text,
            context_text=body.context_text,
            target_language_code=body.target_language_code,
            lesson_id=body.lesson_id,
        )
    except service.AIDisabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="ai_disabled") from None
    except (ProviderUnavailable, ProviderRejected):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="ai_provider_error") from None
    except service.AIEmptyResponse:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="ai_empty_response") from None
    return TranslateResponse(
        hints=[HintOut(text=h) for h in result.hints],
        model=result.model,
        latency_ms=result.latency_ms,
    )
