"""Application settings loaded from environment variables.

All Flinq configuration lives in a single Pydantic model. See `.env.example`
at the repo root for the full list of variables.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FLINQ_",
        extra="ignore",
    )

    env: Literal["dev", "prod", "test"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    secret_key: str = Field(default="change-me", min_length=8)

    # Database
    database_url: str = "postgresql+asyncpg://flinq:flinq@localhost:5432/flinq"

    # Redis (Taskiq broker + ephemeral cache)
    redis_url: str = "redis://localhost:6379/0"

    # LLM provider (ADR-0003)
    llm_enabled: bool = False
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 30

    # OCR service (optional external dependency, see architecture §5.1)
    ocr_enabled: bool = False
    ocr_base_url: str = ""
    ocr_api_key: str = ""

    # Frontend static assets (production only)
    static_dir: Path | None = None

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()