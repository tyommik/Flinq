"""Pydantic DTOs for reader-state APIs (spec §API-1: tokenized lesson content).

Wire keys `t/n/i/ws/p` are the wire contract consumed byte-for-byte by the
frontend reader — do not rename.
"""

from __future__ import annotations

import uuid
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WordToken(BaseModel):
    t: str
    n: str
    i: int


class WhitespaceToken(BaseModel):
    ws: str


class PunctToken(BaseModel):
    p: str


Token = WordToken | WhitespaceToken | PunctToken


class SentenceOut(BaseModel):
    seg_id: uuid.UUID
    index: int  # sentence ordinal (segment.ordinal)
    text: str
    normalized_text: str
    tokens: list[Token]


class ParagraphOut(BaseModel):
    sentences: list[SentenceOut]


class LessonContentResponse(BaseModel):
    lesson_id: uuid.UUID
    language_code: str
    word_count: int
    paragraphs: list[ParagraphOut]


class TokenStatusOut(BaseModel):
    s: str
    c: int | None = None


class TokenStatusesResponse(BaseModel):
    statuses: dict[str, TokenStatusOut]


class ReaderPositionPut(BaseModel):
    lesson_id: uuid.UUID
    view_mode: Literal["page", "sentence"]
    current_segment_id: uuid.UUID | None
    current_token_ordinal: int | None = Field(default=None, ge=0)


class ReaderPositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    view_mode: str
    current_segment_id: uuid.UUID | None
    current_token_ordinal: int | None


class BulkKnownRequest(BaseModel):
    lesson_id: uuid.UUID
    from_ordinal: int = Field(ge=0)
    to_ordinal: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.to_ordinal < self.from_ordinal:
            raise ValueError("to_ordinal must be >= from_ordinal")
        return self


class BulkKnownResponse(BaseModel):
    action_id: uuid.UUID
    created_count: int


class BulkUndoResponse(BaseModel):
    undone_count: int


class SegmentTranslationRequest(BaseModel):
    target_language_code: Literal["en", "ru", "pt"]


class SegmentTranslationResponse(BaseModel):
    text: str
    source: str
    model: str
    stored: bool
