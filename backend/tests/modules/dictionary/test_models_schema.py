"""Schema invariants: active-pair uniqueness, cascade delete (spec Decision 1)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.dictionary.models import (
    DictionaryEntry,
    DictionaryExample,
    DictionarySourceVersion,
    DictionaryTranslation,
)


def _version(status: str = "importing") -> DictionarySourceVersion:
    return DictionarySourceVersion(
        source_name="wiktionary-kaikki",
        source_language_code="en",
        target_language_code="ru",
        source_version="test-dump",
        status=status,
    )


async def test_only_one_active_version_per_pair(db_session: AsyncSession) -> None:
    db_session.add(_version("active"))
    await db_session.flush()
    db_session.add(_version("active"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_importing_versions_do_not_conflict(db_session: AsyncSession) -> None:
    db_session.add_all([_version("importing"), _version("importing"), _version("failed")])
    await db_session.flush()


async def test_delete_version_cascades_to_entries_and_translations(
    db_session: AsyncSession,
) -> None:
    v = _version()
    db_session.add(v)
    await db_session.flush()
    e = DictionaryEntry(
        source_version_id=v.id,
        source_language_code="en",
        headword="building",
        headword_normalized="building",
        part_of_speech="noun",
        entry_key="building:noun:0",
        gloss_summary="a structure",
    )
    db_session.add(e)
    await db_session.flush()
    db_session.add(
        DictionaryTranslation(
            entry_id=e.id, target_language_code="ru", translation_text="здание", sense_index=0
        )
    )
    db_session.add(
        DictionaryExample(
            entry_id=e.id,
            sense_index=0,
            example_text="The building is tall.",
            example_translation="Здание высокое.",
        )
    )
    await db_session.flush()
    entry_id = e.id

    await db_session.delete(v)
    await db_session.flush()
    # DB-level ON DELETE CASCADE removes the rows, but the ORM identity map
    # still holds stale references from before the delete; expire everything
    # so the assertions below re-query the database instead of serving them.
    # (entry_id is captured above since expired attribute access requires an
    # awaited reload and can't happen implicitly on a bare attribute get.)
    db_session.expire_all()
    count = await db_session.scalar(select(func.count()).select_from(DictionaryTranslation))
    assert count == 0
    example_count = await db_session.scalar(select(func.count()).select_from(DictionaryExample))
    assert example_count == 0
    assert await db_session.get(DictionaryEntry, entry_id) is None
