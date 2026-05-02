"""Pydantic DTOs for the identity module (auth + me endpoints)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

SUPPORTED_LEARNING_LANGUAGES = frozenset({"en", "ru", "pt"})
SUPPORTED_UI_LANGUAGES = frozenset({"en", "ru"})


class RegisterRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = True


class OnboardingRequest(BaseModel):
    ui_language: str
    learning_languages: list[str] = Field(min_length=1)
    translation_language: str

    @field_validator("ui_language")
    @classmethod
    def _ui_language_supported(cls, v: str) -> str:
        if v not in SUPPORTED_UI_LANGUAGES:
            raise ValueError(f"unsupported UI language: {v}")
        return v

    @field_validator("learning_languages")
    @classmethod
    def _learning_languages_supported(cls, v: list[str]) -> list[str]:
        for code in v:
            if code not in SUPPORTED_LEARNING_LANGUAGES:
                raise ValueError(f"unsupported learning language: {code}")
        return v

    @field_validator("translation_language")
    @classmethod
    def _translation_language_supported(cls, v: str) -> str:
        if v not in SUPPORTED_LEARNING_LANGUAGES:
            raise ValueError(f"unsupported translation language: {v}")
        return v


class DeleteMeRequest(BaseModel):
    password: str


class SetLastLanguageRequest(BaseModel):
    language_code: str

    @field_validator("language_code")
    @classmethod
    def _supported(cls, v: str) -> str:
        if v not in SUPPORTED_LEARNING_LANGUAGES:
            raise ValueError(f"unsupported language: {v}")
        return v


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: Literal["learner", "admin"]
    display_name: str
    ui_language_code: str
    learning_languages: list[str]
    last_learning_language_code: str | None
    needs_onboarding: bool
    onboarded_at: datetime | None
