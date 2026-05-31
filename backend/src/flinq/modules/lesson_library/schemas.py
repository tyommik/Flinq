"""Pydantic DTOs for lessons API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from flinq.modules.identity.schemas import SUPPORTED_LEARNING_LANGUAGES


class CreateLessonRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    language_code: str
    raw_text: str = Field(min_length=1)
    visibility: Literal["private", "shared"] = "private"

    @field_validator("language_code")
    @classmethod
    def _supported(cls, v: str) -> str:
        if v not in SUPPORTED_LEARNING_LANGUAGES:
            raise ValueError(f"unsupported language: {v}")
        return v


class LessonSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    language_code: str
    word_count: int
    visibility: str
    status: str
    created_at: datetime


class LessonListResponse(BaseModel):
    items: list[LessonSummary]
    total: int
    page: int
    page_size: int


class LessonCreatedResponse(BaseModel):
    id: uuid.UUID
    status: str


class LessonStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    language_code: str
    status: str
    word_count: int
    segment_count: int
    visibility: str
    created_at: datetime
