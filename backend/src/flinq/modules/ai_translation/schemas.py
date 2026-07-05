"""Request/response models for the AI translate endpoint."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    surface_text: str = Field(min_length=1, max_length=256)
    context_text: str = Field(min_length=1, max_length=1000)
    target_language_code: Literal["en", "ru", "pt"]
    lesson_id: uuid.UUID | None = None


class HintOut(BaseModel):
    text: str


class TranslateResponse(BaseModel):
    hints: list[HintOut]
    model: str
    latency_ms: int
