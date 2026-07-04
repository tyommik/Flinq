"""Dictionary lookup API (spec Decision 6)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.dictionary.links import render_external_links
from flinq.modules.dictionary.provider import WIKTIONARY_ATTRIBUTION, WiktionaryLocalProvider
from flinq.modules.dictionary.schemas import DictionaryLookupResponse, ExternalLinkOut

router = APIRouter(prefix="/api/dictionary", tags=["dictionary"])

LangCode = Literal["en", "ru", "pt"]


def _require_user(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user_id


@router.get("/lookup", response_model=DictionaryLookupResponse)
async def lookup(
    request: Request,
    lang: LangCode,
    target: LangCode,
    text: Annotated[str, Query(min_length=1, max_length=256)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DictionaryLookupResponse:
    _require_user(request)
    entries = await WiktionaryLocalProvider(session).lookup(text, lang, target)
    links = [
        ExternalLinkOut(name=link.name, url=link.url)
        for link in render_external_links(text, lang, target)
    ]
    return DictionaryLookupResponse(
        entries=entries, attribution=WIKTIONARY_ATTRIBUTION, external_links=links
    )
