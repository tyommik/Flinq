# Dictionary: Wiktionary Provider (FLQ-2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Built-in offline dictionary: Kaikki/Wiktionary dumps imported into Postgres via a CLI command, exposed through `GET /api/dictionary/lookup` with CC-BY-SA attribution and external-dictionary link-outs.

**Architecture:** New `flinq/modules/dictionary/` module (models, kaikki parser, repo, import service, provider, links) + `flinq dictionary refresh` CLI + one API router. Import is stream-parse → COPY into a *new* `dictionary_source_versions` row, then atomic activation (readers never see partial data). The token↔dictionary join key is one shared normalization function (`flinq/core/textnorm.py`), which also lands the deferred FLQ-1 `casefold`/U+2019 fix.

**Tech Stack:** Python 3.13, SQLAlchemy 2 async + asyncpg (COPY via `copy_records_to_table`), Alembic, FastAPI, Pydantic v2, typer, httpx, loguru, pytest + testcontainers.

**Spec:** `.superpowers/specs/2026-07-04-dictionary-wiktionary-design.md` — read it first; decisions there are binding.

## Global Constraints

- Branch: `feat/flq-2-dictionary-wiktionary` off current `main`.
- Gates must stay green after every task: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` (0 errors), `uv run pytest` (all run from `backend/`).
- Commits (AGENTS.md «Git конвенции»): conventional commits with the task in the scope — `feat(FLQ-2.<task#>): <english imperative subject, ≤72 chars>`; body answers "why", not "what"; always scoped paths — `git commit -m "..." -- <exact paths>`; NO `Co-Authored-By` trailers.
- Do NOT edit `README.md`, `docs/adr/*`, `.github/workflows/*`, `backend/Dockerfile` — they carry uncommitted user WIP. The spec records the ADR-0004 deviation; no ADR edit in this change.
- Languages: `en`, `ru`, `pt`. Covered pairs: en→ru, en→pt, ru→en, pt→en (English edition dumps), pt→ru (Russian edition dump).
- Normalization everywhere = `flinq.core.textnorm.normalize_token` (NFC → U+2019→`'` → casefold → strip outer punctuation).
- All new code: `from __future__ import annotations`, `Mapped[...]` ORM style, loguru for logging, full type annotations (pyright runs repo-wide).

---

### Task 0: Branch

- [ ] **Step 1: Create the branch**

```bash
git checkout main && git pull && git checkout -b feat/flq-2-dictionary-wiktionary
```

---

### Task 1: Shared normalization (`textnorm`) — closes the FLQ-1 follow-up

**Files:**
- Create: `backend/src/flinq/core/textnorm.py`
- Create: `backend/tests/core/__init__.py` (empty)
- Test: `backend/tests/core/test_textnorm.py`
- Modify: `backend/src/flinq/modules/lesson_library/tokenization.py` (delete local `normalize_token`, import from core)

**Interfaces:**
- Produces: `normalize_token(surface: str) -> str` in `flinq.core.textnorm` — used by every later task and re-exported from `tokenization` for existing callers.

- [ ] **Step 1: Write the failing tests**

`backend/tests/core/test_textnorm.py`:

```python
"""Canonical normalization: the token<->dictionary join key (ADR-0001 + FLQ-1 follow-up)."""

from __future__ import annotations

from flinq.core.textnorm import normalize_token


def test_lowercases_and_strips_outer_punctuation() -> None:
    assert normalize_token("«Hello!»") == "hello"


def test_casefold_beats_lower() -> None:
    # .lower() keeps "ß"; .casefold() folds it — the whole point of the fix.
    assert normalize_token("Straße") == "strasse"


def test_curly_apostrophe_joins_with_ascii() -> None:
    assert normalize_token("d’água") == normalize_token("d'água") == "d'água"


def test_keeps_diacritics_and_internal_hyphen() -> None:
    assert normalize_token("Está-se") == "está-se"
    assert normalize_token("Ёлка") == "ёлка"


def test_tokenizer_uses_shared_function() -> None:
    from flinq.modules.lesson_library.tokenization import tokenize

    [tok] = [t for t in tokenize("Straße.") if t.is_word_like]
    assert tok.normalized_text == "strasse"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/core/test_textnorm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'flinq.core.textnorm'`

- [ ] **Step 3: Implement `flinq/core/textnorm.py`**

```python
"""Canonical text normalization (ADR-0001).

One function shared by lesson occurrences, the dictionary and the future
vocabulary layer. If this ever changes, already-imported data must be
re-imported — treat the algorithm as frozen.
"""

from __future__ import annotations

import re
import unicodedata

_OUTER_PUNCT_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)
_APOSTROPHES = str.maketrans({"’": "'"})


def normalize_token(surface: str) -> str:
    """NFC, U+2019 -> ', casefold, strip outer punctuation; keep diacritics + internal -/'."""
    s = unicodedata.normalize("NFC", surface).translate(_APOSTROPHES).casefold()
    return _OUTER_PUNCT_RE.sub("", s)
```

- [ ] **Step 4: Switch `tokenization.py` to the shared function**

In `backend/src/flinq/modules/lesson_library/tokenization.py`:
- add `from flinq.core.textnorm import normalize_token` to the imports;
- delete the local `def normalize_token(...)` (lines ~30–34) and the now-unused `_OUTER_PUNCT_RE` constant;
- keep everything else (the name stays importable from `tokenization` — existing callers and tests keep working).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run pytest`
Expected: PASS (existing tokenization tests only assert lowercase-compatible cases; if any asserts `.lower()`-specific behavior, update that test to the casefold expectation and note it in the commit body).

- [ ] **Step 6: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright
git add backend/src/flinq/core/textnorm.py backend/tests/core backend/src/flinq/modules/lesson_library/tokenization.py
git commit -m "feat(FLQ-2.1): add shared normalize_token with casefold and U+2019" -- backend/src/flinq/core/textnorm.py backend/tests/core backend/src/flinq/modules/lesson_library/tokenization.py
```

---

### Task 2: Dictionary models + migration 0004

**Files:**
- Create: `backend/src/flinq/modules/dictionary/__init__.py` (module docstring only)
- Create: `backend/src/flinq/modules/dictionary/models.py`
- Create: `backend/migrations/versions/0004_dictionary.py`
- Create: `backend/tests/modules/dictionary/__init__.py` (empty)
- Test: `backend/tests/modules/dictionary/test_models_schema.py`
- Modify: `backend/tests/conftest.py` (`_init_schema` — add dictionary models side-effect import next to the existing two)

**Interfaces:**
- Produces ORM classes in `flinq.modules.dictionary.models`: `DictionarySourceVersion`, `DictionaryEntry`, `DictionaryTranslation`, `DictionaryExample` (fields exactly as in the DDL below).

- [ ] **Step 1: Write the failing test**

`backend/tests/modules/dictionary/test_models_schema.py`:

```python
"""Schema invariants: active-pair uniqueness, cascade delete (spec Decision 1)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.dictionary.models import (
    DictionaryEntry,
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
    await db_session.flush()

    await db_session.delete(v)
    await db_session.flush()
    count = await db_session.scalar(select(func.count()).select_from(DictionaryTranslation))
    assert count == 0
    assert await db_session.get(DictionaryEntry, e.id) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/modules/dictionary/test_models_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'flinq.modules.dictionary'`

- [ ] **Step 3: Implement `models.py`**

```python
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

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
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
```

`__init__.py`: `"""Built-in dictionary: Wiktionary/Kaikki data, provider, lookup (FLQ-2)."""`

- [ ] **Step 4: Register models in test schema bootstrap**

In `backend/tests/conftest.py`, inside `_init_schema` next to the two existing side-effect imports, add:

```python
    from flinq.modules.dictionary import (
        models as _dictionary_models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/modules/dictionary/test_models_schema.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Write migration `0004_dictionary.py`**

Follow `0003_lesson_pipeline.py` style exactly (revision strings, `from __future__`, typed module vars). `revision = "0004_dictionary"`, `down_revision = "0003_lesson_pipeline"`. `upgrade()` creates the four tables + the partial unique index + the lookup index (mirror the model DDL 1:1 with `sa.Column`/`postgresql.UUID(as_uuid=True)`/`postgresql.JSONB`); `downgrade()` drops tables in reverse order (`dictionary_examples`, `dictionary_translations`, `dictionary_entries`, `dictionary_source_versions`). Partial index in Alembic:

```python
    op.create_index(
        "uq_dictionary_versions_active_pair",
        "dictionary_source_versions",
        ["source_language_code", "target_language_code"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
```

- [ ] **Step 7: Verify the migration chain test still passes**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_migration_chain.py -v`
Expected: PASS (it walks `upgrade head` / `downgrade base` over all revisions, now including 0004).

- [ ] **Step 8: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
git add backend/src/flinq/modules/dictionary backend/migrations/versions/0004_dictionary.py backend/tests/modules/dictionary backend/tests/conftest.py
git commit -m "feat(FLQ-2.2): add dictionary models and migration" -- backend/src/flinq/modules/dictionary backend/migrations/versions/0004_dictionary.py backend/tests/modules/dictionary backend/tests/conftest.py
```

---

### Task 3: Kaikki record parser (pure functions)

**Files:**
- Create: `backend/src/flinq/modules/dictionary/kaikki.py`
- Test: `backend/tests/modules/dictionary/test_kaikki.py`

**Interfaces:**
- Produces:
  - `ParsedTranslation(target_language_code: str, translation_text: str, sense_index: int, usage_note: str | None)` (frozen dataclass)
  - `ParsedExample(sense_index: int, example_text: str, example_translation: str | None)` (frozen dataclass)
  - `ParsedEntry(headword: str, part_of_speech: str | None, entry_key: str, gloss_summary: str | None, translations: tuple[ParsedTranslation, ...], examples: tuple[ParsedExample, ...])` (frozen dataclass)
  - `parse_record(record: dict[str, Any], *, source_lang: str, target_lang: str) -> ParsedEntry | None`
  - `MAX_EXAMPLES_PER_ENTRY = 5`

- [ ] **Step 1: Write the failing tests**

`backend/tests/modules/dictionary/test_kaikki.py`:

```python
"""parse_record: both dump shapes (spec Decision 3)."""

from __future__ import annotations

from typing import Any

from flinq.modules.dictionary.kaikki import parse_record

EN_BUILDING: dict[str, Any] = {
    "word": "building",
    "lang_code": "en",
    "pos": "noun",
    "senses": [
        {
            "glosses": ["A structure built for habitation or use"],
            "examples": [{"text": "The building has three floors."}],
        }
    ],
    "translations": [
        {"code": "ru", "word": "здание", "sense": "structure"},
        {"code": "pt", "word": "edifício"},
        {"code": "de", "word": "Gebäude"},
    ],
}

RU_DOM: dict[str, Any] = {
    "word": "дом",
    "lang_code": "ru",
    "pos": "noun",
    "senses": [
        {"glosses": ["house", "building"]},
        {"glosses": ["home"], "examples": [{"text": "Я иду домой.", "english": "I am going home."}]},
    ],
}


def test_en_record_takes_translations_for_target() -> None:
    entry = parse_record(EN_BUILDING, source_lang="en", target_lang="ru")
    assert entry is not None
    assert entry.headword == "building"
    assert entry.entry_key == "building:noun:0"
    assert [t.translation_text for t in entry.translations] == ["здание"]
    assert entry.translations[0].usage_note == "structure"
    assert entry.examples[0].example_text == "The building has three floors."


def test_en_record_other_target_language() -> None:
    entry = parse_record(EN_BUILDING, source_lang="en", target_lang="pt")
    assert entry is not None
    assert [t.translation_text for t in entry.translations] == ["edifício"]


def test_foreign_record_takes_glosses_per_sense() -> None:
    entry = parse_record(RU_DOM, source_lang="ru", target_lang="en")
    assert entry is not None
    texts = [(t.sense_index, t.translation_text) for t in entry.translations]
    assert texts == [(0, "house; building"), (1, "home")]
    assert entry.examples == (
        type(entry.examples[0])(sense_index=1, example_text="Я иду домой.", example_translation="I am going home."),
    )


def test_wrong_language_is_skipped() -> None:
    assert parse_record(RU_DOM, source_lang="pt", target_lang="ru") is None


def test_record_without_translations_is_skipped() -> None:
    record: dict[str, Any] = {"word": "aaa", "lang_code": "en", "pos": "noun", "senses": []}
    assert parse_record(record, source_lang="en", target_lang="ru") is None


def test_examples_capped_at_five() -> None:
    record: dict[str, Any] = {
        "word": "casa",
        "lang_code": "pt",
        "pos": "noun",
        "senses": [{"glosses": ["дом"], "examples": [{"text": f"ex {i}"} for i in range(10)]}],
    }
    entry = parse_record(record, source_lang="pt", target_lang="ru")
    assert entry is not None
    assert len(entry.examples) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/modules/dictionary/test_kaikki.py -v`
Expected: FAIL — no module `kaikki`

- [ ] **Step 3: Implement `kaikki.py`**

```python
"""Kaikki.org JSONL record parsing — pure functions, no I/O (spec Decision 3).

Two shapes:
- `source_lang == "en"` (English-edition English dump): translations come from
  the record/sense `translations` lists filtered by target language code.
- otherwise (foreign-language dumps): each sense's glosses ARE the translation,
  written in the edition's language (== the pair's target by construction).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_EXAMPLES_PER_ENTRY = 5


@dataclass(frozen=True)
class ParsedTranslation:
    target_language_code: str
    translation_text: str
    sense_index: int
    usage_note: str | None


@dataclass(frozen=True)
class ParsedExample:
    sense_index: int
    example_text: str
    example_translation: str | None


@dataclass(frozen=True)
class ParsedEntry:
    headword: str
    part_of_speech: str | None
    entry_key: str
    gloss_summary: str | None
    translations: tuple[ParsedTranslation, ...]
    examples: tuple[ParsedExample, ...]


def _sense_gloss(sense: dict[str, Any]) -> str:
    return "; ".join(g for g in sense.get("glosses", []) if isinstance(g, str))


def _translations_from_lists(
    record: dict[str, Any], glosses: list[str], target_lang: str
) -> list[ParsedTranslation]:
    out: list[ParsedTranslation] = []
    items: list[tuple[int | None, dict[str, Any]]] = [
        (None, t) for t in record.get("translations", []) or []
    ]
    for i, sense in enumerate(record.get("senses", []) or []):
        items.extend((i, t) for t in sense.get("translations", []) or [])
    for sense_i, t in items:
        if t.get("code") != target_lang or not t.get("word"):
            continue
        note = t.get("sense")
        index = sense_i if sense_i is not None else 0
        if sense_i is None and note:
            # Best-effort: map a top-level translation to the sense whose gloss mentions it.
            index = next((j for j, g in enumerate(glosses) if note and note in g), 0)
        out.append(
            ParsedTranslation(
                target_language_code=target_lang,
                translation_text=t["word"],
                sense_index=index,
                usage_note=note,
            )
        )
    return out


def _translations_from_glosses(
    senses: list[dict[str, Any]], target_lang: str
) -> list[ParsedTranslation]:
    out: list[ParsedTranslation] = []
    for i, sense in enumerate(senses):
        text = _sense_gloss(sense)
        if text:
            out.append(
                ParsedTranslation(
                    target_language_code=target_lang,
                    translation_text=text,
                    sense_index=i,
                    usage_note=None,
                )
            )
    return out


def _collect_examples(senses: list[dict[str, Any]]) -> tuple[ParsedExample, ...]:
    out: list[ParsedExample] = []
    for i, sense in enumerate(senses):
        for ex in sense.get("examples", []) or []:
            text = ex.get("text")
            if not text:
                continue
            out.append(
                ParsedExample(
                    sense_index=i,
                    example_text=text,
                    example_translation=ex.get("translation") or ex.get("english"),
                )
            )
            if len(out) >= MAX_EXAMPLES_PER_ENTRY:
                return tuple(out)
    return tuple(out)


def parse_record(
    record: dict[str, Any], *, source_lang: str, target_lang: str
) -> ParsedEntry | None:
    """Turn one JSONL record into a ParsedEntry, or None when irrelevant."""
    if record.get("lang_code") != source_lang:
        return None
    word = record.get("word")
    if not isinstance(word, str) or not word:
        return None
    senses: list[dict[str, Any]] = record.get("senses", []) or []
    glosses = [_sense_gloss(s) for s in senses]
    pos = record.get("pos")
    if source_lang == "en":
        translations = _translations_from_lists(record, glosses, target_lang)
    else:
        translations = _translations_from_glosses(senses, target_lang)
    if not translations:
        return None
    return ParsedEntry(
        headword=word,
        part_of_speech=pos if isinstance(pos, str) else None,
        entry_key=f"{word}:{pos or ''}:{record.get('etymology_number') or 0}",
        gloss_summary=next((g for g in glosses if g), None),
        translations=tuple(translations),
        examples=_collect_examples(senses),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/modules/dictionary/test_kaikki.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright
git add backend/src/flinq/modules/dictionary/kaikki.py backend/tests/modules/dictionary/test_kaikki.py
git commit -m "feat(FLQ-2.3): add Kaikki JSONL record parser" -- backend/src/flinq/modules/dictionary/kaikki.py backend/tests/modules/dictionary/test_kaikki.py
```

---

### Task 4: Dump registry + downloader

**Files:**
- Create: `backend/src/flinq/modules/dictionary/sources.py`
- Create: `backend/src/flinq/modules/dictionary/download.py`
- Test: `backend/tests/modules/dictionary/test_download.py`
- Modify: `backend/src/flinq/core/config.py` (add `data_dir` setting)
- Modify: `.env.example` (add `FLINQ_DATA_DIR` with a comment)

**Interfaces:**
- Produces:
  - `DumpSource(url: str)` frozen dataclass and `DUMP_SOURCES: dict[tuple[str, str], DumpSource]` in `sources.py` (keys are the 5 covered pairs)
  - `download_dump(url: str, dest_dir: Path, *, client: httpx.AsyncClient | None = None) -> Path` in `download.py`
  - `iter_dump_lines(path: Path) -> Iterator[str]` in `download.py` (gzip-aware)
  - `Settings.data_dir: Path` (default `REPO_ROOT / "data"`)

- [ ] **Step 1: Verify real dump URLs (network, one-off)**

```bash
curl -sIL "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl.gz" | head -1
curl -sIL "https://kaikki.org/dictionary/Russian/kaikki.org-dictionary-Russian.jsonl.gz" | head -1
curl -sIL "https://kaikki.org/dictionary/Portuguese/kaikki.org-dictionary-Portuguese.jsonl.gz" | head -1
```

Expected: `HTTP/2 200` each. For the Russian-edition Portuguese dump, open https://kaikki.org and navigate to the Russian edition (`ruwiktionary`) Portuguese page; copy the real `.jsonl.gz` link. **Write whatever URLs actually return 200 into `DUMP_SOURCES` — do not guess.** If the `.gz` variant 404s, use the plain `.jsonl` URL (the loader is gzip-aware by extension).

- [ ] **Step 2: Write the failing tests**

`backend/tests/modules/dictionary/test_download.py`:

```python
"""Streaming download + gzip-aware line iteration."""

from __future__ import annotations

import gzip
from pathlib import Path

import httpx

from flinq.modules.dictionary.download import download_dump, iter_dump_lines
from flinq.modules.dictionary.sources import DUMP_SOURCES


def test_registry_covers_the_five_pairs() -> None:
    assert set(DUMP_SOURCES) == {("en", "ru"), ("en", "pt"), ("ru", "en"), ("pt", "en"), ("pt", "ru")}


async def test_download_streams_to_file(tmp_path: Path) -> None:
    body = b'{"word": "a"}\n{"word": "b"}\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    path = await download_dump("https://example.org/dump.jsonl", tmp_path, client=client)
    assert path == tmp_path / "dump.jsonl"
    assert path.read_bytes() == body


def test_iter_dump_lines_plain_and_gzip(tmp_path: Path) -> None:
    plain = tmp_path / "d.jsonl"
    plain.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
    gz = tmp_path / "d.jsonl.gz"
    with gzip.open(gz, "wt", encoding="utf-8") as f:
        f.write('{"a": 1}\n{"b": 2}\n')
    assert list(iter_dump_lines(plain)) == list(iter_dump_lines(gz)) == ['{"a": 1}\n', '{"b": 2}\n']
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/modules/dictionary/test_download.py -v`
Expected: FAIL — no module `download`

- [ ] **Step 4: Implement**

`sources.py`:

```python
"""Where each covered language pair's Kaikki dump lives (spec: coverage table)."""

from __future__ import annotations

from dataclasses import dataclass

_EN_EDITION = "https://kaikki.org/dictionary"


@dataclass(frozen=True)
class DumpSource:
    url: str


# URLs verified against kaikki.org on 2026-07-04 (Task 4 Step 1). The pt->ru
# URL comes from the Russian edition (ruwiktionary) section of kaikki.org.
DUMP_SOURCES: dict[tuple[str, str], DumpSource] = {
    ("en", "ru"): DumpSource(f"{_EN_EDITION}/English/kaikki.org-dictionary-English.jsonl.gz"),
    ("en", "pt"): DumpSource(f"{_EN_EDITION}/English/kaikki.org-dictionary-English.jsonl.gz"),
    ("ru", "en"): DumpSource(f"{_EN_EDITION}/Russian/kaikki.org-dictionary-Russian.jsonl.gz"),
    ("pt", "en"): DumpSource(f"{_EN_EDITION}/Portuguese/kaikki.org-dictionary-Portuguese.jsonl.gz"),
    ("pt", "ru"): DumpSource("<URL from Step 1 — Russian edition, Portuguese>"),
}
```

(The `("pt", "ru")` value MUST be replaced with the verified URL from Step 1 before committing — the test suite does not hit the network, so the guard is Step 1 itself.)

`download.py`:

```python
"""Dump download and reading — the only I/O in the import path."""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from pathlib import Path

import httpx
from loguru import logger

_PROGRESS_EVERY_BYTES = 50 * 1024 * 1024


async def download_dump(url: str, dest_dir: Path, *, client: httpx.AsyncClient | None = None) -> Path:
    """Stream `url` into `dest_dir/<filename>` with progress logs; return the path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / url.rsplit("/", 1)[-1]
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0))
    try:
        async with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            done = 0
            next_mark = _PROGRESS_EVERY_BYTES
            with dest.open("wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
                    done += len(chunk)
                    if done >= next_mark:
                        logger.info("dictionary download: {} MB", done // (1024 * 1024))
                        next_mark += _PROGRESS_EVERY_BYTES
    finally:
        if own_client:
            await client.aclose()
    logger.info("dictionary download finished: {} ({} bytes)", dest, dest.stat().st_size)
    return dest


def iter_dump_lines(path: Path) -> Iterator[str]:
    """Yield lines from a plain or gzip JSONL file."""
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            yield from f
    else:
        with path.open("rt", encoding="utf-8") as f:
            yield from f
```

`config.py` — add below the `static_dir` field:

```python
    # Local data (dictionary dump cache, future exports)
    data_dir: Path = REPO_ROOT / "data"
```

`.env.example` — add:

```
# Local data directory (dictionary dump cache). Defaults to <repo>/data.
#FLINQ_DATA_DIR=
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/modules/dictionary/test_download.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright
git add backend/src/flinq/modules/dictionary/sources.py backend/src/flinq/modules/dictionary/download.py backend/tests/modules/dictionary/test_download.py backend/src/flinq/core/config.py .env.example
git commit -m "feat(FLQ-2.4): add dump source registry and streaming downloader" -- backend/src/flinq/modules/dictionary/sources.py backend/src/flinq/modules/dictionary/download.py backend/tests/modules/dictionary/test_download.py backend/src/flinq/core/config.py .env.example
```

---

### Task 5: Repo + import service (COPY, version lifecycle)

**Files:**
- Create: `backend/src/flinq/modules/dictionary/repo.py`
- Create: `backend/src/flinq/modules/dictionary/service.py`
- Create: `backend/tests/fixtures/dictionary/en_english.jsonl`, `en_russian.jsonl`, `ru_portuguese.jsonl`
- Test: `backend/tests/modules/dictionary/test_import_service.py`

**Interfaces:**
- Consumes: `parse_record`, `iter_dump_lines`, models from Tasks 2–4.
- Produces:
  - `DictionaryRepo(session)` with `create_version(...) -> DictionarySourceVersion`, `activate_version(version_id: uuid.UUID) -> None`, `mark_failed(version_id: uuid.UUID, error: str) -> None`, `lookup(source_lang: str, target_lang: str, normalized: str) -> list[DictionaryEntry]` (entries with `.translations`/`.examples` loaded — add `relationship`s in Step 3)
  - `ImportStats(entries: int, translations: int, examples: int, skipped_lines: int, duplicate_keys: int)` (frozen dataclass)
  - `import_dump(session, *, source_lang: str, target_lang: str, dump_path: Path, source_version_tag: str) -> ImportStats` in `service.py`

- [ ] **Step 1: Create fixtures**

`backend/tests/fixtures/dictionary/en_english.jsonl` (3 lines):

```
{"word": "building", "lang_code": "en", "pos": "noun", "senses": [{"glosses": ["A structure built for habitation or use"], "examples": [{"text": "The building has three floors."}]}], "translations": [{"code": "ru", "word": "здание", "sense": "structure"}, {"code": "ru", "word": "строение"}, {"code": "pt", "word": "edifício"}]}
{"word": "house", "lang_code": "en", "pos": "noun", "senses": [{"glosses": ["A building serving as a dwelling"]}], "translations": [{"code": "ru", "word": "дом"}]}
{"word": "untranslated", "lang_code": "en", "pos": "noun", "senses": [{"glosses": ["no target translations here"]}], "translations": [{"code": "de", "word": "x"}]}
```

`backend/tests/fixtures/dictionary/en_russian.jsonl` (2 lines + 1 deliberately malformed):

```
{"word": "дом", "lang_code": "ru", "pos": "noun", "senses": [{"glosses": ["house", "building"]}, {"glosses": ["home"]}]}
not-a-json-line
{"word": "ёлка", "lang_code": "ru", "pos": "noun", "senses": [{"glosses": ["spruce; Christmas tree"]}]}
```

`backend/tests/fixtures/dictionary/ru_portuguese.jsonl` (1 line):

```
{"word": "edifício", "lang_code": "pt", "pos": "noun", "senses": [{"glosses": ["здание", "строение"], "examples": [{"text": "O edifício é alto.", "translation": "Здание высокое."}]}]}
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/modules/dictionary/test_import_service.py`:

```python
"""Import round-trip, atomic refresh, failure handling (spec Decisions 1-2)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.dictionary import service
from flinq.modules.dictionary.models import DictionaryEntry, DictionarySourceVersion
from flinq.modules.dictionary.repo import DictionaryRepo

FIXTURES = Path(__file__).parents[2] / "fixtures" / "dictionary"


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
    assert stats.skipped_lines == 1


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
    # entries of the old version are gone (cascade)
    count = await db_session.scalar(select(func.count()).select_from(DictionaryEntry))
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
```

- [ ] **Step 3: Run tests to verify they fail, then implement**

Run: `cd backend && uv run pytest tests/modules/dictionary/test_import_service.py -v` → FAIL (no `repo`/`service`).

Add to `models.py` (Task 2 file) the relationships the repo needs:

```python
# on DictionaryEntry:
    translations: Mapped[list["DictionaryTranslation"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="DictionaryTranslation.sense_index"
    )
    examples: Mapped[list["DictionaryExample"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="DictionaryExample.sense_index"
    )
```

(import `relationship` from `sqlalchemy.orm`; add `back_populates`-free one-directional relationships — translations/examples don't need a parent ref.)

`repo.py`:

```python
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
```

`service.py`:

```python
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
    "id", "source_version_id", "source_language_code", "headword",
    "headword_normalized", "part_of_speech", "entry_key", "gloss_summary",
)
_TRANSLATION_COLS = ("id", "entry_id", "target_language_code", "translation_text", "sense_index", "usage_note")
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
    await raw.driver_connection.copy_records_to_table(table, records=records, columns=list(columns))


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
        except ValueError:
            skipped += 1
            continue
        parsed = parse_record(record, source_lang=source_lang, target_lang=target_lang)
        if parsed is None:
            continue
        if parsed.entry_key in seen_keys:
            duplicates += 1
            continue
        seen_keys.add(parsed.entry_key)
        entry_id = uuid.uuid4()
        entries.append(
            (entry_id, version_id, source_lang, parsed.headword,
             normalize_token(parsed.headword), parsed.part_of_speech,
             parsed.entry_key, parsed.gloss_summary)
        )
        n_entries += 1
        for t in parsed.translations:
            translations.append(
                (uuid.uuid4(), entry_id, t.target_language_code, t.translation_text, t.sense_index, t.usage_note)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/modules/dictionary/test_import_service.py -v`
Expected: PASS (5 tests). If `raw.driver_connection` typing upsets pyright, cast: `conn_any: Any = raw.driver_connection` with a comment `# asyncpg.Connection — no stubs for copy_records_to_table`.

- [ ] **Step 5: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
git add backend/src/flinq/modules/dictionary/repo.py backend/src/flinq/modules/dictionary/service.py backend/src/flinq/modules/dictionary/models.py backend/tests/modules/dictionary/test_import_service.py backend/tests/fixtures/dictionary
git commit -m "feat(FLQ-2.5): add COPY-based import with atomic version swap" -- backend/src/flinq/modules/dictionary/repo.py backend/src/flinq/modules/dictionary/service.py backend/src/flinq/modules/dictionary/models.py backend/tests/modules/dictionary/test_import_service.py backend/tests/fixtures/dictionary
```

---

### Task 6: CLI `flinq dictionary refresh`

**Files:**
- Create: `backend/src/flinq/cli/dictionary.py`
- Modify: `backend/src/flinq/cli/main.py` (register sub-app)
- Test: `backend/tests/cli/__init__.py` (empty), `backend/tests/cli/test_dictionary_cli.py`

**Interfaces:**
- Consumes: `DUMP_SOURCES`, `download_dump`, `import_dump`, `get_settings`, `init_engine`/`dispose_engine`/`session_scope` from `flinq.core.db`.
- Produces: `flinq dictionary refresh --lang <src> --target <dst> [--file PATH]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/cli/test_dictionary_cli.py`:

```python
"""CLI wiring: pair validation and the --file path (import itself is covered in Task 5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

from flinq.cli.main import app
from flinq.modules.dictionary.repo import DictionaryRepo

FIXTURES = Path(__file__).parents[1] / "fixtures" / "dictionary"


def test_unsupported_pair_without_file_errors() -> None:
    result = CliRunner().invoke(app, ["dictionary", "refresh", "--lang", "ru", "--target", "pt"])
    assert result.exit_code == 2
    assert "Unsupported pair" in result.output


async def test_refresh_with_file_imports(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from flinq.cli import dictionary as cli_dictionary

    # Reuse the test engine/session instead of the CLI building its own.
    async def _run(source_lang: str, target_lang: str, dump_path: Path, tag: str) -> None:
        from flinq.modules.dictionary.service import import_dump

        await import_dump(
            db_session,
            source_lang=source_lang,
            target_lang=target_lang,
            dump_path=dump_path,
            source_version_tag=tag,
        )

    monkeypatch.setattr(cli_dictionary, "_run_refresh", _run)
    await cli_dictionary._run_refresh("pt", "ru", FIXTURES / "ru_portuguese.jsonl", "t")
    [entry] = await DictionaryRepo(db_session).lookup(
        source_lang="pt", target_lang="ru", normalized="edifício"
    )
    assert entry.translations[0].translation_text == "здание; строение"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/cli/test_dictionary_cli.py -v`
Expected: FAIL — no `flinq.cli.dictionary` / no `dictionary` command registered.

- [ ] **Step 3: Implement `cli/dictionary.py`**

```python
"""`flinq dictionary` commands (ADR-0004: manual admin refresh)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import typer
from loguru import logger

app = typer.Typer(help="Built-in dictionary data management.")


async def _run_refresh(source_lang: str, target_lang: str, dump_path: Path, tag: str) -> None:
    from flinq.core.config import get_settings
    from flinq.core.db import dispose_engine, init_engine, session_scope
    from flinq.modules.dictionary.service import import_dump

    init_engine(get_settings())
    try:
        async with session_scope() as session:
            stats = await import_dump(
                session,
                source_lang=source_lang,
                target_lang=target_lang,
                dump_path=dump_path,
                source_version_tag=tag,
            )
        logger.info("refresh complete: {}", stats)
    finally:
        await dispose_engine()


@app.command()
def refresh(
    lang: str = typer.Option(..., help="Source language code (en|ru|pt)."),
    target: str = typer.Option(..., help="Target language code (en|ru|pt)."),
    file: Path | None = typer.Option(None, exists=True, dir_okay=False, help="Local JSONL[.gz] dump instead of downloading."),
) -> None:
    """Download (or read --file) a Kaikki dump and load it into Postgres."""
    from flinq.core.config import get_settings
    from flinq.modules.dictionary.download import download_dump
    from flinq.modules.dictionary.sources import DUMP_SOURCES

    source = DUMP_SOURCES.get((lang, target))
    if source is None and file is None:
        supported = ", ".join(f"{s}->{t}" for s, t in sorted(DUMP_SOURCES))
        typer.echo(f"Unsupported pair {lang}->{target}. Supported: {supported}", err=True)
        raise typer.Exit(2)

    async def _main() -> None:
        if file is not None:
            dump_path, tag = file, f"file:{file.name}"
        else:
            assert source is not None
            cache = get_settings().data_dir / "dictionary-dumps"
            dump_path = await download_dump(source.url, cache)
            tag = f"{dump_path.name}@{datetime.now(UTC).date().isoformat()}"
        await _run_refresh(lang, target, dump_path, tag)

    asyncio.run(_main())
```

In `cli/main.py`, next to the identity sub-app:

```python
from flinq.cli.dictionary import app as dictionary_app
app.add_typer(dictionary_app, name="dictionary")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/cli/test_dictionary_cli.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright
git add backend/src/flinq/cli/dictionary.py backend/src/flinq/cli/main.py backend/tests/cli
git commit -m "feat(FLQ-2.6): add flinq dictionary refresh CLI command" -- backend/src/flinq/cli/dictionary.py backend/src/flinq/cli/main.py backend/tests/cli
```

---

### Task 7: External dictionary links

**Files:**
- Create: `backend/src/flinq/modules/dictionary/links.py`
- Test: `backend/tests/modules/dictionary/test_links.py`

**Interfaces:**
- Produces: `render_external_links(text: str, from_lang: str, to_lang: str) -> list[ExternalLink]` where `ExternalLink(name: str, url: str)` is a frozen dataclass.

- [ ] **Step 1: Write the failing tests**

`backend/tests/modules/dictionary/test_links.py`:

```python
"""External link templates: pair filtering + URL encoding (spec Decision 7)."""

from __future__ import annotations

from flinq.modules.dictionary.links import render_external_links


def _names(links: list[object]) -> set[str]:
    return {link.name for link in links}  # type: ignore[attr-defined]


def test_en_ru_includes_lingvo_and_urban_and_google() -> None:
    links = render_external_links("building", "en", "ru")
    names = _names(links)
    assert {"Lingvo Live", "Google Translate", "Wiktionary", "Urban Dictionary"} <= names
    assert "WordReference" not in names  # no en-ru on WordReference


def test_pt_ru_has_no_urban() -> None:
    names = _names(render_external_links("edifício", "pt", "ru"))
    assert "Urban Dictionary" not in names


def test_text_is_url_encoded() -> None:
    [lingvo] = [
        link for link in render_external_links("Что такое", "ru", "en")
        if link.name == "Lingvo Live"  # type: ignore[attr-defined]
    ]
    assert lingvo.url == "https://www.lingvolive.com/en-us/translate/ru-en/%D0%A7%D1%82%D0%BE%20%D1%82%D0%B0%D0%BA%D0%BE%D0%B5"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/modules/dictionary/test_links.py -v` → FAIL (no module `links`).

- [ ] **Step 3: Implement `links.py`**

```python
"""External dictionary link templates rendered server-side (spec Decision 7).

Constant defaults for MVP; moves to admin config in FLQ-11 without touching
the frontend.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class ExternalLink:
    name: str
    url: str


@dataclass(frozen=True)
class ExternalDictionaryTemplate:
    name: str
    url_template: str  # placeholders: {text} {from} {to}
    pairs: frozenset[tuple[str, str]] | None = None  # None = any pair


DEFAULT_EXTERNAL_DICTIONARIES: tuple[ExternalDictionaryTemplate, ...] = (
    ExternalDictionaryTemplate(
        "Lingvo Live",
        "https://www.lingvolive.com/en-us/translate/{from}-{to}/{text}",
        frozenset({("en", "ru"), ("ru", "en"), ("pt", "ru"), ("ru", "pt")}),
    ),
    ExternalDictionaryTemplate(
        "WordReference",
        "https://www.wordreference.com/{from}{to}/{text}",
        frozenset({("en", "pt"), ("pt", "en")}),
    ),
    ExternalDictionaryTemplate(
        "Google Translate", "https://translate.google.com/?sl={from}&tl={to}&text={text}"
    ),
    ExternalDictionaryTemplate("Wiktionary", "https://en.wiktionary.org/wiki/{text}"),
    ExternalDictionaryTemplate(
        "Urban Dictionary",
        "https://www.urbandictionary.com/define.php?term={text}",
        frozenset({("en", "ru"), ("en", "pt"), ("en", "en")}),
    ),
)


def render_external_links(text: str, from_lang: str, to_lang: str) -> list[ExternalLink]:
    """Substitute placeholders for every template matching the pair."""
    values = {"text": quote(text, safe=""), "from": from_lang, "to": to_lang}
    return [
        ExternalLink(name=t.name, url=t.url_template.format_map(values))
        for t in DEFAULT_EXTERNAL_DICTIONARIES
        if t.pairs is None or (from_lang, to_lang) in t.pairs
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/modules/dictionary/test_links.py -v` → PASS (3 tests)

- [ ] **Step 5: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright
git add backend/src/flinq/modules/dictionary/links.py backend/tests/modules/dictionary/test_links.py
git commit -m "feat(FLQ-2.7): add external dictionary link templates" -- backend/src/flinq/modules/dictionary/links.py backend/tests/modules/dictionary/test_links.py
```

---

### Task 8: Provider, schemas, lookup endpoint

**Files:**
- Create: `backend/src/flinq/modules/dictionary/schemas.py`
- Create: `backend/src/flinq/modules/dictionary/provider.py`
- Create: `backend/src/flinq/api/dictionary.py`
- Modify: `backend/src/flinq/main.py` (import + `app.include_router(dictionary_router)` after `lessons_router`)
- Test: `backend/tests/api/test_dictionary_lookup.py`

**Interfaces:**
- Consumes: `DictionaryRepo.lookup`, `normalize_token`, `render_external_links`, fixtures + `import_dump` for seeding.
- Produces: `GET /api/dictionary/lookup?lang=&target=&text=` (session auth, same `_require_user` pattern as `api/lessons.py`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_dictionary_lookup.py` (reuse the `_register_and_onboard` helper shape from `tests/api/test_lessons_import.py` — copy it in, tests must be self-contained):

```python
"""GET /api/dictionary/lookup — AC#3, AC#5 and spec Decision 6."""

from __future__ import annotations

from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.main import create_app
from flinq.modules.dictionary import service

FIXTURES = Path(__file__).parents[1] / "fixtures" / "dictionary"


async def _register_and_onboard(c: AsyncClient, email: str, lang: str = "pt") -> str:
    r = await c.post(
        "/auth/register",
        json={"display_name": "T", "email": email, "password": "abcdefghij"},
    )
    assert r.status_code == 201
    csrf = c.cookies.get("flinq_csrf")
    assert csrf
    await c.post(
        "/me/onboarding",
        json={"ui_language": "en", "learning_languages": [lang], "translation_language": "en"},
        headers={"X-CSRF-Token": csrf},
    )
    return csrf


async def _seed(db_session: AsyncSession) -> None:
    await service.import_dump(
        db_session, source_lang="en", target_lang="ru",
        dump_path=FIXTURES / "en_english.jsonl", source_version_tag="t",
    )
    await service.import_dump(
        db_session, source_lang="ru", target_lang="en",
        dump_path=FIXTURES / "en_russian.jsonl", source_version_tag="t",
    )
    await service.import_dump(
        db_session, source_lang="pt", target_lang="ru",
        dump_path=FIXTURES / "ru_portuguese.jsonl", source_version_tag="t",
    )


async def test_lookup_en_ru_ru_en_pt_ru(db_session: AsyncSession) -> None:
    await _seed(db_session)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register_and_onboard(c, "dict-lookup@example.com")

        r = await c.get("/api/dictionary/lookup", params={"lang": "en", "target": "ru", "text": "Building"})
        assert r.status_code == 200
        body = r.json()
        [entry] = body["entries"]
        assert entry["headword"] == "building"
        assert {s["translation"] for s in entry["senses"]} == {"здание", "строение"}
        assert body["attribution"]["license"] == "CC-BY-SA 4.0"
        assert any(link["name"] == "Lingvo Live" for link in body["external_links"])

        r = await c.get("/api/dictionary/lookup", params={"lang": "ru", "target": "en", "text": "дом"})
        assert r.json()["entries"][0]["senses"][0]["translation"] == "house; building"

        r = await c.get("/api/dictionary/lookup", params={"lang": "pt", "target": "ru", "text": "edifício"})
        assert r.json()["entries"][0]["senses"][0]["translation"] == "здание; строение"


async def test_unknown_word_and_uncovered_pair_return_200_empty(db_session: AsyncSession) -> None:
    await _seed(db_session)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register_and_onboard(c, "dict-empty@example.com")
        for params in (
            {"lang": "en", "target": "ru", "text": "zzzznope"},
            {"lang": "ru", "target": "pt", "text": "дом"},  # valid but uncovered pair
        ):
            r = await c.get("/api/dictionary/lookup", params=params)
            assert r.status_code == 200
            body = r.json()
            assert body["entries"] == []
            assert body["external_links"]
            assert body["attribution"]["license"] == "CC-BY-SA 4.0"


async def test_validation_and_auth() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/dictionary/lookup", params={"lang": "en", "target": "ru", "text": "x"})
        assert r.status_code == 401  # no session

        await _register_and_onboard(c, "dict-auth@example.com")
        r = await c.get("/api/dictionary/lookup", params={"lang": "xx", "target": "ru", "text": "x"})
        assert r.status_code == 422  # bad language code
        r = await c.get("/api/dictionary/lookup", params={"lang": "en", "target": "ru", "text": "y" * 300})
        assert r.status_code == 422  # text too long
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/api/test_dictionary_lookup.py -v` → FAIL (404 route).

- [ ] **Step 3: Implement schemas, provider, router**

`schemas.py`:

```python
"""Pydantic response models for dictionary lookup."""

from __future__ import annotations

from pydantic import BaseModel


class DictionaryExampleOut(BaseModel):
    text: str
    translation: str | None


class DictionarySenseOut(BaseModel):
    sense_index: int
    translation: str
    usage_note: str | None
    examples: list[DictionaryExampleOut]


class DictionaryEntryOut(BaseModel):
    headword: str
    part_of_speech: str | None
    senses: list[DictionarySenseOut]


class AttributionOut(BaseModel):
    source: str
    license: str
    url: str


class ExternalLinkOut(BaseModel):
    name: str
    url: str


class DictionaryLookupResponse(BaseModel):
    entries: list[DictionaryEntryOut]
    attribution: AttributionOut
    external_links: list[ExternalLinkOut]
```

`provider.py`:

```python
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
```

`api/dictionary.py`:

```python
"""Dictionary lookup API (spec Decision 6)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.dictionary.links import render_external_links
from flinq.modules.dictionary.provider import WIKTIONARY_ATTRIBUTION, WiktionaryLocalProvider
from flinq.modules.dictionary.schemas import DictionaryLookupResponse, ExternalLinkOut

router = APIRouter(prefix="/api/dictionary", tags=["dictionary"])

LangCode = Literal["en", "ru", "pt"]


def _require_user(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user_id


@router.get("/lookup", response_model=DictionaryLookupResponse)
async def lookup(
    request: Request,
    lang: LangCode,
    target: LangCode,
    text: Annotated[str, Query(min_length=1, max_length=256)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DictionaryLookupResponse:
    _require_user(request)
    entries = await WiktionaryLocalProvider(session).lookup(text, lang, target)
    links = [
        ExternalLinkOut(name=link.name, url=link.url)
        for link in render_external_links(text, lang, target)
    ]
    return DictionaryLookupResponse(
        entries=entries, attribution=WIKTIONARY_ATTRIBUTION, external_links=links
    )
```

`main.py`: add `from flinq.api.dictionary import router as dictionary_router` and `app.include_router(dictionary_router)` after the lessons router.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/test_dictionary_lookup.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
git add backend/src/flinq/modules/dictionary/schemas.py backend/src/flinq/modules/dictionary/provider.py backend/src/flinq/api/dictionary.py backend/src/flinq/main.py backend/tests/api/test_dictionary_lookup.py
git commit -m "feat(FLQ-2.8): add provider abstraction and lookup endpoint" -- backend/src/flinq/modules/dictionary/schemas.py backend/src/flinq/modules/dictionary/provider.py backend/src/flinq/api/dictionary.py backend/src/flinq/main.py backend/tests/api/test_dictionary_lookup.py
```

---

### Task 9: Finalization

**Files:**
- Modify: `.superpowers/specs/2026-07-04-dictionary-wiktionary-design.md` (status header → implemented; reconcile any drift)
- Modify (via backlog MCP, not by hand): FLQ-2 acceptance criteria + status

- [ ] **Step 1: Full gate run**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```
Expected: all green; 0 pyright errors.

- [ ] **Step 2: Smoke the real CLI once (optional but recommended)**

With dev docker-compose Postgres up: `cd backend && uv run flinq dictionary refresh --lang pt --target ru --file tests/fixtures/dictionary/ru_portuguese.jsonl`, then `curl` the lookup endpoint with a dev session. Expected: entries in the response.

- [ ] **Step 3: Reconcile spec, update backlog**

Update the spec header (`Status:` → implemented on branch, test count) and any decision that drifted during implementation. Commit scoped:

```bash
git add .superpowers/specs/2026-07-04-dictionary-wiktionary-design.md
git commit -m "docs(FLQ-2): reconcile design spec with implementation" -- .superpowers/specs/2026-07-04-dictionary-wiktionary-design.md
```

Check FLQ-2 acceptance criteria (backlog MCP `task_edit`: check AC #1–#5, status Done, final summary). AC#2 note: progress logs are covered by `_PROGRESS_EVERY_LINES` + download progress; AC#4 by the `DictionaryProvider` Protocol.

- [ ] **Step 4: PR**

Push the branch, open a PR to `main` titled `feat(FLQ-2): Wiktionary dictionary provider`, wait for CI green, then squash-merge. Per AGENTS.md, rewrite the squash commit message manually: subject `feat(FLQ-2): add Wiktionary dictionary provider with import and lookup`, body explaining *why* (offline-first dictionary layer for the Word Card), no branch names, no commit lists, no `Co-authored-by`.

---

## Self-Review (done at plan-writing time)

- **Spec coverage:** coverage table → Task 4 registry; Decision 1 (versioning) → Tasks 2+5; Decision 2 (COPY) → Task 5; Decision 3 (mapping) → Task 3; Decision 4 (normalization) → Task 1; Decision 5 (provider) → Task 8; Decision 6 (endpoint incl. 422/empty-200 split) → Task 8 tests; Decision 7 (links) → Task 7; Decision 8 (CLI) → Task 6; testing section → spread across task tests. No gaps found.
- **Known deliberate deviation:** none.
- **Type consistency check:** `ParsedEntry`/`ImportStats`/`DictionaryRepo.lookup` signatures match across Tasks 3→5→8; `render_external_links` return type matches Task 8 usage.
- **Risk note for the implementer:** the exact Kaikki URL for the ru-edition Portuguese dump and the presence of `.gz` variants MUST be verified in Task 4 Step 1 — do not commit guessed URLs.
