"""Vocabulary WordCard API (FLQ-5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.vocabulary import service
from flinq.modules.vocabulary.models import PersonalTranslation
from flinq.modules.vocabulary.schemas import (
    AddTagRequest,
    AddTranslationRequest,
    BulkActionRequest,
    BulkActionResponse,
    CreateItemRequest,
    ItemStateResponse,
    LookupResponse,
    NoteResponse,
    PatchItemRequest,
    PrimaryTranslationOut,
    PutNoteRequest,
    TagsResponse,
    TranslationListResponse,
    TranslationOut,
    TranslationsBlock,
    UpdateTranslationRequest,
    VocabListItemOut,
    VocabListResponse,
)

router = APIRouter(prefix="/api/vocabulary", tags=["vocabulary"])

LangCode = Literal["en", "ru", "pt"]
Kind = Literal["token", "phrase"]


def _require_user(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user_id


def _translation_out(t: PersonalTranslation) -> TranslationOut:
    return TranslationOut(
        id=t.id,
        text=t.translation_text,
        target_language_code=t.target_language_code,
        is_primary=t.is_primary,
        source_type=t.source_type,
    )


@router.get("/lookup", response_model=LookupResponse)
async def lookup(
    request: Request,
    lang: LangCode,
    text: Annotated[str, Query(min_length=1, max_length=256)],
    target: LangCode,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LookupResponse:
    user_id = _require_user(request)
    res = await service.lookup(
        session,
        user_id=user_id,
        language_code=lang,
        text=text,
        target_language_code=target,
    )
    return LookupResponse(
        item_id=res.item_id,
        status=cast('Literal["new", "tracked", "known", "ignored"]', res.status),
        confidence=res.confidence,
        translations=TranslationsBlock(
            primary=_translation_out(res.primary) if res.primary else None,
            all=[_translation_out(t) for t in res.translations],
        ),
        note=res.note,
        tags=res.tags,
    )


@router.post("/items", status_code=201, response_model=ItemStateResponse)
async def create_item(
    request: Request,
    body: CreateItemRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ItemStateResponse:
    user_id = _require_user(request)
    item = await service.create_item(
        session,
        user_id=user_id,
        kind=body.kind,
        language_code=body.language_code,
        text=body.text,
        status=body.status,
        confidence=body.confidence,
    )
    return ItemStateResponse(item_id=item.id, status=item.status, confidence=item.confidence)


def _resolve(kind: str) -> None:
    if kind != "token":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unsupported item kind")


@router.patch("/items/{kind}/{item_id}", response_model=ItemStateResponse)
async def patch_item(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    body: PatchItemRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ItemStateResponse:
    user_id = _require_user(request)
    _resolve(kind)
    try:
        item = await service.patch_item(
            session,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            status=body.status,
            confidence=body.confidence,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return ItemStateResponse(item_id=item.id, status=item.status, confidence=item.confidence)


@router.post("/items/{kind}/{item_id}/translations", response_model=TranslationOut)
async def add_translation(
    request: Request,
    response: Response,
    kind: Kind,
    item_id: uuid.UUID,
    body: AddTranslationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranslationOut:
    user_id = _require_user(request)
    _resolve(kind)
    try:
        row, created = await service.add_translation(
            session,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            target_language_code=body.target_language_code,
            translation_text=body.translation_text,
            source_type=body.source_type,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _translation_out(row)


@router.patch(
    "/items/{kind}/{item_id}/translations/{translation_id}", response_model=TranslationOut
)
async def update_translation(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    translation_id: uuid.UUID,
    body: UpdateTranslationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranslationOut:
    user_id = _require_user(request)
    _resolve(kind)
    try:
        row = await service.update_translation(
            session,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            translation_id=translation_id,
            translation_text=body.translation_text,
        )
    except (service.ItemNotFound, service.TranslationNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    except service.DuplicateTranslation:
        raise HTTPException(status.HTTP_409_CONFLICT, "duplicate translation text") from None
    return _translation_out(row)


@router.delete(
    "/items/{kind}/{item_id}/translations/{translation_id}",
    response_model=TranslationListResponse,
)
async def delete_translation(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    translation_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranslationListResponse:
    user_id = _require_user(request)
    _resolve(kind)
    try:
        rows = await service.delete_translation(
            session,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            translation_id=translation_id,
        )
    except (service.ItemNotFound, service.TranslationNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return TranslationListResponse(translations=[_translation_out(t) for t in rows])


@router.put("/items/{kind}/{item_id}/notes", response_model=NoteResponse)
async def put_note(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    body: PutNoteRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NoteResponse:
    user_id = _require_user(request)
    _resolve(kind)
    try:
        row = await service.put_note(
            session,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            note_text=body.note_text,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return NoteResponse(note=row.note_text)


@router.post("/items/{kind}/{item_id}/tags", response_model=TagsResponse)
async def add_tag(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    body: AddTagRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TagsResponse:
    user_id = _require_user(request)
    _resolve(kind)
    try:
        tags = await service.add_tag(
            session,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            tag_name=body.tag_name,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return TagsResponse(tags=tags)


@router.delete("/items/{kind}/{item_id}/tags/{tag_name}", response_model=TagsResponse)
async def remove_tag(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    tag_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TagsResponse:
    user_id = _require_user(request)
    _resolve(kind)
    try:
        tags = await service.remove_tag(
            session,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            tag_name=tag_name,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return TagsResponse(tags=tags)


@router.get("", response_model=VocabListResponse)
async def list_vocabulary(
    request: Request,
    lang: LangCode,
    session: Annotated[AsyncSession, Depends(get_session)],
    target: LangCode = "ru",
    kind: Literal["token", "all"] = "all",
    status_filter: Annotated[
        list[Literal["tracked", "known", "ignored"]] | None, Query(alias="status")
    ] = None,
    confidence_min: Annotated[int | None, Query(ge=0, le=5)] = None,
    confidence_max: Annotated[int | None, Query(ge=0, le=5)] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=128)] = None,
    added_after: datetime | None = None,
    sort: Literal["created_at", "text"] = "created_at",
    sort_dir: Literal["asc", "desc"] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query()] = 25,
    added_by: Literal["user", "all"] = "user",
) -> VocabListResponse:
    if page_size not in (25, 50, 100):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "page_size must be 25, 50 or 100")
    user_id = _require_user(request)
    items, total = await service.list_items(
        session,
        user_id=user_id,
        language_code=lang,
        target_language_code=target,
        kind=kind,
        statuses=list(status_filter) if status_filter else ["tracked", "known", "ignored"],
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        tags=list(tag) if tag else [],
        q=q,
        added_after=added_after,
        sort=sort,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
        added_by=added_by,
    )
    return VocabListResponse(
        items=[
            VocabListItemOut(
                item_id=i.item_id,
                kind="token",
                text=i.text,
                status=cast('Literal["tracked", "known", "ignored"]', i.status),
                confidence=i.confidence,
                primary_translation=(
                    PrimaryTranslationOut(
                        text=i.primary_translation_text,
                        target_language_code=i.primary_translation_target or target,
                    )
                    if i.primary_translation_text is not None
                    else None
                ),
                tags=i.tags,
                pos=i.pos,
                context=i.context,
                created_at=cast(datetime, i.created_at),
            )
            for i in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/bulk", response_model=BulkActionResponse)
async def bulk(
    request: Request,
    body: BulkActionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BulkActionResponse:
    user_id = _require_user(request)
    affected = await service.bulk_action(
        session,
        user_id=user_id,
        item_ids=body.item_ids,
        action=body.action,
        tag_name=body.tag_name,
    )
    return BulkActionResponse(affected=affected)
