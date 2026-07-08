"""Pydantic DTOs for the vocabulary WordCard API (FLQ-5)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

LangCode = Literal["en", "ru", "pt"]
ItemStatus = Literal["tracked", "known", "ignored"]


class TranslationOut(BaseModel):
    id: uuid.UUID
    text: str
    target_language_code: str
    is_primary: bool
    source_type: str


class TranslationsBlock(BaseModel):
    primary: TranslationOut | None
    all: list[TranslationOut]


class LookupResponse(BaseModel):
    item_id: uuid.UUID | None
    status: Literal["new", "tracked", "known", "ignored"]
    confidence: int | None
    translations: TranslationsBlock
    note: str | None
    tags: list[str]


class CreateItemRequest(BaseModel):
    kind: Literal["token"] = "token"
    language_code: LangCode
    text: str = Field(min_length=1, max_length=256)
    status: ItemStatus
    confidence: int | None = Field(default=None, ge=0, le=5)

    @model_validator(mode="after")
    def _confidence_matches_status(self) -> CreateItemRequest:
        if (self.status == "tracked") != (self.confidence is not None):
            raise ValueError("confidence required iff status == 'tracked'")
        return self


class PatchItemRequest(BaseModel):
    status: ItemStatus
    confidence: int | None = Field(default=None, ge=0, le=5)

    @model_validator(mode="after")
    def _confidence_matches_status(self) -> PatchItemRequest:
        if (self.status == "tracked") != (self.confidence is not None):
            raise ValueError("confidence required iff status == 'tracked'")
        return self


class ItemStateResponse(BaseModel):
    item_id: uuid.UUID
    status: str
    confidence: int | None


class AddTranslationRequest(BaseModel):
    target_language_code: LangCode
    translation_text: str = Field(min_length=1, max_length=512)
    source_type: Literal["user", "ai", "dictionary"] = "user"


class UpdateTranslationRequest(BaseModel):
    translation_text: str = Field(min_length=1, max_length=512)


class TranslationListResponse(BaseModel):
    translations: list[TranslationOut]


class PutNoteRequest(BaseModel):
    note_text: str = Field(max_length=4000)


class NoteResponse(BaseModel):
    note: str


class AddTagRequest(BaseModel):
    tag_name: str = Field(min_length=1, max_length=64)


class TagsResponse(BaseModel):
    tags: list[str]
