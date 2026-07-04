"""Dump import: stream-parse -> COPY -> atomic version activation (spec Decisions 1-2)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.textnorm import normalize_token
from flinq.modules.dictionary.download import iter_dump_lines
from flinq.modules.dictionary.kaikki import parse_record
from flinq.modules.dictionary.repo import DictionaryRepo

BATCH_SIZE = 5000
_PROGRESS_EVERY_LINES = 100_000

_ENTRY_COLS = (
    "id",
    "source_version_id",
    "source_language_code",
    "headword",
    "headword_normalized",
    "part_of_speech",
    "entry_key",
    "gloss_summary",
)
_TRANSLATION_COLS = (
    "id",
    "entry_id",
    "target_language_code",
    "translation_text",
    "sense_index",
    "usage_note",
)
_EXAMPLE_COLS = ("id", "entry_id", "sense_index", "example_text", "example_translation")


@dataclass(frozen=True)
class ImportStats:
    entries: int
    translations: int
    examples: int
    skipped_lines: int
    duplicate_keys: int


async def _copy_records(
    session: AsyncSession, table: str, columns: tuple[str, ...], records: list[tuple[Any, ...]]
) -> None:
    if not records:
        return
    conn = await session.connection()
    raw = await conn.get_raw_connection()
    conn_any: Any = raw.driver_connection  # asyncpg.Connection — no stubs for copy_records_to_table
    await conn_any.copy_records_to_table(table, records=records, columns=list(columns))


async def import_dump(
    session: AsyncSession,
    *,
    source_lang: str,
    target_lang: str,
    dump_path: Path,
    source_version_tag: str,
) -> ImportStats:
    repo = DictionaryRepo(session)
    version = await repo.create_version(
        source_name="wiktionary-kaikki",
        source_lang=source_lang,
        target_lang=target_lang,
        source_version=source_version_tag,
        metadata={"dump_path": str(dump_path)},
    )
    await session.commit()
    try:
        stats = await _load_dump(session, version.id, source_lang, target_lang, dump_path)
        await repo.activate_version(version.id)
        version.metadata_json = {**version.metadata_json, "stats": stats.__dict__}
        await session.commit()
    except Exception as exc:
        await session.rollback()
        await repo.mark_failed(version.id, str(exc))
        await session.commit()
        raise
    logger.info("dictionary import {}->{} done: {}", source_lang, target_lang, stats)
    return stats


async def _load_dump(
    session: AsyncSession,
    version_id: uuid.UUID,
    source_lang: str,
    target_lang: str,
    dump_path: Path,
) -> ImportStats:
    entries: list[tuple[Any, ...]] = []
    translations: list[tuple[Any, ...]] = []
    examples: list[tuple[Any, ...]] = []
    seen_keys: set[str] = set()
    n_entries = n_translations = n_examples = skipped = duplicates = 0

    async def flush() -> None:
        nonlocal entries, translations, examples
        await _copy_records(session, "dictionary_entries", _ENTRY_COLS, entries)
        await _copy_records(session, "dictionary_translations", _TRANSLATION_COLS, translations)
        await _copy_records(session, "dictionary_examples", _EXAMPLE_COLS, examples)
        entries, translations, examples = [], [], []

    for line_no, line in enumerate(iter_dump_lines(dump_path), start=1):
        try:
            record = json.loads(line)
            parsed = parse_record(record, source_lang=source_lang, target_lang=target_lang)
        except (ValueError, AttributeError, TypeError):
            skipped += 1
            continue
        if parsed is None:
            continue
        if parsed.entry_key in seen_keys:
            duplicates += 1
            continue
        seen_keys.add(parsed.entry_key)
        entry_id = uuid.uuid4()
        entries.append(
            (
                entry_id,
                version_id,
                source_lang,
                parsed.headword,
                normalize_token(parsed.headword),
                parsed.part_of_speech,
                parsed.entry_key,
                parsed.gloss_summary,
            )
        )
        n_entries += 1
        for t in parsed.translations:
            translations.append(
                (
                    uuid.uuid4(),
                    entry_id,
                    t.target_language_code,
                    t.translation_text,
                    t.sense_index,
                    t.usage_note,
                )
            )
            n_translations += 1
        for ex in parsed.examples:
            examples.append(
                (uuid.uuid4(), entry_id, ex.sense_index, ex.example_text, ex.example_translation)
            )
            n_examples += 1
        if len(entries) >= BATCH_SIZE:
            await flush()
        if line_no % _PROGRESS_EVERY_LINES == 0:
            logger.info("dictionary import: {} lines read, {} entries", line_no, n_entries)
    await flush()
    return ImportStats(n_entries, n_translations, n_examples, skipped, duplicates)
