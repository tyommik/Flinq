"""Dictionary storage (domain model §9, ADR-0004).

Instance-wide, read-only data imported from Wiktionary/Kaikki dumps.
A version row is scoped to one (source_lang, target_lang) pair; at most one
version per pair is `active` (partial unique index). Entries/translations/
examples hang off a version and die with it (ON DELETE CASCADE).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from flinq.core.db import Base


class DictionarySourceVersion(Base):
    __tablename__ = "dictionary_source_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_name: Mapped[str] = mapped_column(String(64))
    source_language_code: Mapped[str] = mapped_column(String(8))
    target_language_code: Mapped[str] = mapped_column(String(8))
    source_version: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="importing")  # importing|active|failed
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        Index(
            "uq_dictionary_versions_active_pair",
            "source_language_code",
            "target_language_code",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


class DictionaryEntry(Base):
    __tablename__ = "dictionary_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dictionary_source_versions.id", ondelete="CASCADE")
    )
    source_language_code: Mapped[str] = mapped_column(String(8))
    headword: Mapped[str] = mapped_column(Text)
    headword_normalized: Mapped[str] = mapped_column(Text)
    part_of_speech: Mapped[str | None] = mapped_column(String(32))
    entry_key: Mapped[str] = mapped_column(Text)
    gloss_summary: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("source_version_id", "entry_key", name="uq_dictionary_entries_key"),
        Index(
            "ix_dictionary_entries_lookup",
            "source_language_code",
            "headword_normalized",
            "source_version_id",
        ),
    )


class DictionaryTranslation(Base):
    __tablename__ = "dictionary_translations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dictionary_entries.id", ondelete="CASCADE"), index=True
    )
    target_language_code: Mapped[str] = mapped_column(String(8))
    translation_text: Mapped[str] = mapped_column(Text)
    sense_index: Mapped[int] = mapped_column(Integer, default=0)
    usage_note: Mapped[str | None] = mapped_column(Text)


class DictionaryExample(Base):
    __tablename__ = "dictionary_examples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dictionary_entries.id", ondelete="CASCADE"), index=True
    )
    sense_index: Mapped[int] = mapped_column(Integer, default=0)
    example_text: Mapped[str] = mapped_column(Text)
    example_translation: Mapped[str | None] = mapped_column(Text)
