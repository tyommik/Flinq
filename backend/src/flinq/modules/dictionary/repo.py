"""Dictionary persistence: version lifecycle + lookup query."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from flinq.modules.dictionary.models import DictionaryEntry, DictionarySourceVersion


class DictionaryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_version(
        self,
        *,
        source_name: str,
        source_lang: str,
        target_lang: str,
        source_version: str,
        metadata: dict[str, Any] | None = None,
    ) -> DictionarySourceVersion:
        version = DictionarySourceVersion(
            source_name=source_name,
            source_language_code=source_lang,
            target_language_code=target_lang,
            source_version=source_version,
            status="importing",
            metadata_json=metadata or {},
        )
        self.session.add(version)
        await self.session.flush()
        return version

    async def activate_version(self, version_id: uuid.UUID) -> None:
        """Delete all other versions of the pair, then mark this one active."""
        version = await self.session.get_one(DictionarySourceVersion, version_id)
        await self.session.execute(
            delete(DictionarySourceVersion).where(
                DictionarySourceVersion.source_language_code == version.source_language_code,
                DictionarySourceVersion.target_language_code == version.target_language_code,
                DictionarySourceVersion.id != version_id,
            )
        )
        version.status = "active"
        await self.session.flush()

    async def mark_failed(self, version_id: uuid.UUID, error: str) -> None:
        version = await self.session.get_one(DictionarySourceVersion, version_id)
        version.status = "failed"
        version.metadata_json = {**version.metadata_json, "error": error}
        await self.session.flush()

    async def lookup(
        self, *, source_lang: str, target_lang: str, normalized: str
    ) -> list[DictionaryEntry]:
        stmt = (
            select(DictionaryEntry)
            .join(DictionarySourceVersion)
            .where(
                DictionarySourceVersion.status == "active",
                DictionarySourceVersion.source_language_code == source_lang,
                DictionarySourceVersion.target_language_code == target_lang,
                DictionaryEntry.source_language_code == source_lang,
                DictionaryEntry.headword_normalized == normalized,
            )
            .options(
                selectinload(DictionaryEntry.translations),
                selectinload(DictionaryEntry.examples),
            )
            .order_by(DictionaryEntry.entry_key)
        )
        return list((await self.session.scalars(stmt)).all())
