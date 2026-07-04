"""Import round-trip, atomic refresh, failure handling (spec Decisions 1-2)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.dictionary import service
from flinq.modules.dictionary.models import DictionaryEntry, DictionarySourceVersion
from flinq.modules.dictionary.repo import DictionaryRepo

FIXTURES = Path(__file__).parents[2] / "fixtures" / "dictionary"


@pytest.fixture(autouse=True)
async def _clean_dictionary_tables(  # pyright: ignore[reportUnusedFunction] — autouse fixture
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    """Each test hits a real, shared Postgres (no per-test rollback), and
    `DictionarySourceVersion` rows cascade-delete their entries/translations/
    examples. Clear them after every test so this file never leaks active
    versions into `test_models_schema.py` (or between its own tests).
    """
    yield
    await db_session.execute(delete(DictionarySourceVersion))
    await db_session.commit()


async def test_import_en_ru_round_trip(db_session: AsyncSession) -> None:
    stats = await service.import_dump(
        db_session,
        source_lang="en",
        target_lang="ru",
        dump_path=FIXTURES / "en_english.jsonl",
        source_version_tag="fixture-1",
    )
    assert stats.entries == 2  # "untranslated" is skipped (no ru translations)
    assert stats.translations == 3
    repo = DictionaryRepo(db_session)
    [entry] = await repo.lookup(source_lang="en", target_lang="ru", normalized="building")
    assert entry.headword == "building"
    assert sorted(t.translation_text for t in entry.translations) == ["здание", "строение"]
    assert entry.examples[0].example_text == "The building has three floors."


async def test_malformed_lines_are_skipped_not_fatal(db_session: AsyncSession) -> None:
    stats = await service.import_dump(
        db_session,
        source_lang="ru",
        target_lang="en",
        dump_path=FIXTURES / "en_russian.jsonl",
        source_version_tag="fixture-1",
    )
    assert stats.entries == 2
    assert stats.skipped_lines == 2


async def test_second_import_replaces_the_version(db_session: AsyncSession) -> None:
    for tag in ("fixture-1", "fixture-2"):
        await service.import_dump(
            db_session,
            source_lang="en",
            target_lang="ru",
            dump_path=FIXTURES / "en_english.jsonl",
            source_version_tag=tag,
        )
    versions = (
        await db_session.scalars(
            select(DictionarySourceVersion).where(
                DictionarySourceVersion.source_language_code == "en",
                DictionarySourceVersion.target_language_code == "ru",
            )
        )
    ).all()
    assert [v.status for v in versions] == ["active"]
    assert versions[0].source_version == "fixture-2"
    # entries of the old version are gone (cascade). Scoped to this version id
    # (rather than a bare table count) because db_session commits for real against
    # a shared Postgres instance across the whole test session -- other tests'
    # fixtures (e.g. the ru->en malformed-lines import) are not rolled back and
    # would otherwise pollute an unscoped count.
    count = await db_session.scalar(
        select(func.count())
        .select_from(DictionaryEntry)
        .where(DictionaryEntry.source_version_id == versions[0].id)
    )
    assert count == 2


async def test_failed_import_keeps_old_version_active(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await service.import_dump(
        db_session,
        source_lang="en",
        target_lang="ru",
        dump_path=FIXTURES / "en_english.jsonl",
        source_version_tag="fixture-1",
    )

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("copy exploded")

    monkeypatch.setattr(service, "_copy_records", _boom)
    with pytest.raises(RuntimeError):
        await service.import_dump(
            db_session,
            source_lang="en",
            target_lang="ru",
            dump_path=FIXTURES / "en_english.jsonl",
            source_version_tag="fixture-2",
        )
    versions = (await db_session.scalars(select(DictionarySourceVersion))).all()
    statuses = {v.source_version: v.status for v in versions}
    assert statuses == {"fixture-1": "active", "fixture-2": "failed"}


async def test_lookup_unknown_word_is_empty(db_session: AsyncSession) -> None:
    repo = DictionaryRepo(db_session)
    assert await repo.lookup(source_lang="en", target_lang="ru", normalized="nope") == []
