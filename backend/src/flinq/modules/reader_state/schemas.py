"""Pydantic DTOs for reader-state APIs (spec §API-1: tokenized lesson content).

Wire keys `t/n/i/ws/p` are the wire contract consumed byte-for-byte by the
frontend reader — do not rename.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel


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
