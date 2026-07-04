"""DictionaryProvider abstraction (ADR-0004) + the MVP Postgres implementation."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.textnorm import normalize_token
from flinq.modules.dictionary.models import DictionaryEntry
from flinq.modules.dictionary.repo import DictionaryRepo
from flinq.modules.dictionary.schemas import (
    AttributionOut,
    DictionaryEntryOut,
    DictionaryExampleOut,
    DictionarySenseOut,
)

WIKTIONARY_ATTRIBUTION = AttributionOut(
    source="Wiktionary (via Kaikki.org)", license="CC-BY-SA 4.0", url="https://kaikki.org/"
)


class DictionaryProvider(Protocol):
    """Phase-2 providers implement this and register in admin settings."""

    async def lookup(self, text: str, from_lang: str, to_lang: str) -> list[DictionaryEntryOut]: ...


class WiktionaryLocalProvider:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = DictionaryRepo(session)

    async def lookup(self, text: str, from_lang: str, to_lang: str) -> list[DictionaryEntryOut]:
        rows = await self._repo.lookup(
            source_lang=from_lang, target_lang=to_lang, normalized=normalize_token(text)
        )
        return [_to_entry_out(row) for row in rows]


def _to_entry_out(entry: DictionaryEntry) -> DictionaryEntryOut:
    examples_by_sense: dict[int, list[DictionaryExampleOut]] = {}
    for ex in entry.examples:
        examples_by_sense.setdefault(ex.sense_index, []).append(
            DictionaryExampleOut(text=ex.example_text, translation=ex.example_translation)
        )
    senses = [
        DictionarySenseOut(
            sense_index=t.sense_index,
            translation=t.translation_text,
            usage_note=t.usage_note,
            examples=examples_by_sense.get(t.sense_index, []),
        )
        for t in entry.translations
    ]
    return DictionaryEntryOut(
        headword=entry.headword, part_of_speech=entry.part_of_speech, senses=senses
    )
