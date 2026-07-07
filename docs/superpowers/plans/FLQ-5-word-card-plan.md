# FLQ-5 Word Card (Increment 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a real, interactive token Word Card in the reader — user translation, merged suggestions (user/AI/Wiktionary), status+confidence picker, tags and notes — backed by a new `/api/vocabulary` CRUD layer.

**Architecture:** New backend tables (`personal_translations`, `personal_notes`, `item_tags`) polymorphic on `(item_kind, item_id)`, plus a `/api/vocabulary` router over a `service.py` (reader_state-style module functions, session-first, self-committing). Frontend replaces `WordCardPlaceholder` with a real `<WordCard>` driven by TanStack Query; AI and Wiktionary suggestions are fetched by the card from the existing `/api/ai/translate` and `/api/dictionary/lookup` endpoints; the reader highlight becomes `(status, confidence)`-aware.

**Tech Stack:** Backend — FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, pytest + testcontainers. Frontend — React 19, TanStack Query v5, Zustand, Tailwind v4, Vitest + Testing Library.

## Global Constraints

- Python: async SQLAlchemy; every service function takes `session: AsyncSession` first, keyword-only args, and commits on success (reader_state pattern).
- Endpoints get the user via `_require_user(request) -> uuid.UUID` (reads `request.state.user_id`, 401 if missing); DB session via `Depends(get_session)`. No auth dependency object exists — copy `_require_user` into the router.
- CSRF: mutating requests need header `X-CSRF-Token` (frontend `api()` sets it automatically from the `flinq_csrf` cookie; backend tests must pass it explicitly).
- `token_text` is stored ALREADY normalized via `flinq.core.textnorm.normalize_token`. All vocabulary lookups key on the normalized form.
- `confidence` DB range is `0..5` (`ck_token_items_confidence_range`, already applied). Manual UI exposes `1..4` + `✓`(known) + `🗑`(ignored); `0` is system-assigned; `5` is SRS-only. No `token_items` migration.
- Migration head is `0006_reader_state`; the new migration is `0007_vocabulary_card` with `down_revision = "0006_reader_state"`.
- Commit trailer policy: do NOT add `Co-Authored-By`. Commit exact paths (avoid sweeping unrelated staged files).
- LangCode = `Literal["en", "ru", "pt"]`.

## File Structure

**Backend (create):**
- `backend/src/flinq/modules/vocabulary/models.py` — extend with 3 models (already holds `TokenItem`).
- `backend/src/flinq/modules/vocabulary/service.py` — module functions: lookup, item state, translations, notes, tags.
- `backend/src/flinq/modules/vocabulary/schemas.py` — Pydantic DTOs.
- `backend/src/flinq/api/vocabulary.py` — `/api/vocabulary` router.
- `backend/migrations/versions/0007_vocabulary_card.py` — Alembic migration.
- `backend/tests/api/test_vocabulary.py`, `backend/tests/modules/test_vocabulary_service.py`.

**Backend (modify):**
- `backend/src/flinq/main.py` — register `vocabulary_router`.
- `backend/tests/conftest.py` — ensure new models imported for `create_all` (vocabulary.models already imported at `conftest.py:78-80`; new classes live in the same module, so no change needed — verify).

**Frontend (create):**
- `frontend/src/api/vocabulary.ts` — `vocabularyApi` + types.
- `frontend/src/api/dictionary.ts` — thin `dictionaryApi.lookup`.
- `frontend/src/features/reader/useWordCard.ts` — TanStack Query hooks.
- `frontend/src/features/reader/WordCard.tsx` — the component.
- `frontend/src/features/reader/WordCard.test.tsx`.

**Frontend (modify):**
- `frontend/src/features/reader/TokenSpan.tsx` — `(status, confidence)` background.
- `frontend/src/features/reader/TokenSpan.test.tsx` — new cases.
- `frontend/src/features/reader/SentenceView.tsx:155-172` — real vocab chips.
- `frontend/src/features/reader/ReaderPage.tsx` — swap placeholder → WordCard, pass `targetLang`, close-on-lesson-change.
- `frontend/src/api/reader.ts` — (no change; `TokenStatusEntry` already carries `c`).

---

## Task 1: Backend DB layer — vocabulary annotation tables

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/models.py`
- Create: `backend/migrations/versions/0007_vocabulary_card.py`
- Test: `backend/tests/modules/test_vocabulary_service.py` (create; first test is the model round-trip)

**Interfaces:**
- Produces: ORM classes `PersonalTranslation`, `PersonalNote`, `ItemTag` (table names `personal_translations`, `personal_notes`, `item_tags`); Alembic revision `0007_vocabulary_card`.

- [ ] **Step 1: Write the failing test** (model round-trip via a real session)

Create `backend/tests/modules/test_vocabulary_service.py`:

```python
import uuid

import pytest
from sqlalchemy import select

from flinq.core.db import session_scope
from flinq.modules.identity.repo import UserRepo
from flinq.core.security import hash_password
from flinq.modules.vocabulary.models import ItemTag, PersonalNote, PersonalTranslation, TokenItem


async def _make_user(s) -> uuid.UUID:
    user = await UserRepo(s).create(
        email=f"{uuid.uuid4().hex}@t.io", password_hash=hash_password("x"),
        display_name="T", role="learner",
    )
    await s.flush()
    return user.id


@pytest.fixture(autouse=True)
async def _clean():
    yield
    async with session_scope() as s:
        for model in (PersonalTranslation, PersonalNote, ItemTag, TokenItem):
            await s.execute(model.__table__.delete())


async def test_annotation_tables_roundtrip():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = TokenItem(
            user_id=user_id, language_code="pt", token_text="cada",
            status="tracked", confidence=0,
        )
        s.add(item)
        await s.flush()
        s.add(PersonalTranslation(
            owner_user_id=user_id, item_kind="token", item_id=item.id,
            target_language_code="ru", translation_text="каждый",
            is_primary=True, source_type="user",
        ))
        s.add(PersonalNote(
            owner_user_id=user_id, item_kind="token", item_id=item.id, note_text="hi",
        ))
        s.add(ItemTag(
            owner_user_id=user_id, item_kind="token", item_id=item.id, tag_name="verbs",
        ))
        await s.flush()

    async with session_scope() as s:
        tr = (await s.execute(select(PersonalTranslation))).scalars().all()
        assert len(tr) == 1 and tr[0].is_primary is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_service.py::test_annotation_tables_roundtrip -v`
Expected: FAIL — `ImportError: cannot import name 'PersonalTranslation'`.

- [ ] **Step 3: Add the models**

Append to `backend/src/flinq/modules/vocabulary/models.py` (imports `Boolean` is needed — add to the existing `from sqlalchemy import (...)` block):

```python
class PersonalTranslation(Base):
    __tablename__ = "personal_translations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    item_kind: Mapped[str] = mapped_column(String(16))  # 'token' | 'phrase'
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    target_language_code: Mapped[str] = mapped_column(String(8))
    translation_text: Mapped[str] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    source_type: Mapped[str] = mapped_column(String(16))  # user | ai | dictionary
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_personal_translations_item", "owner_user_id", "item_kind", "item_id"),
        Index(
            "uq_personal_translations_primary",
            "owner_user_id", "item_kind", "item_id", "target_language_code",
            unique=True, postgresql_where=text("is_primary"),
        ),
    )


class PersonalNote(Base):
    __tablename__ = "personal_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    item_kind: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    note_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "owner_user_id", "item_kind", "item_id", name="uq_personal_notes_item"
        ),
    )


class ItemTag(Base):
    __tablename__ = "item_tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    item_kind: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    tag_name: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint(
            "owner_user_id", "item_kind", "item_id", "tag_name", name="uq_item_tags"
        ),
    )
```

Update the top-of-file import block to include `Boolean` and `text`:
`from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text)`

- [ ] **Step 4: Write the migration**

Create `backend/migrations/versions/0007_vocabulary_card.py`:

```python
"""vocabulary card annotations

Revision ID: 0007_vocabulary_card
Revises: 0006_reader_state
Create Date: 2026-07-07 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_vocabulary_card"
down_revision: str | Sequence[str] | None = "0006_reader_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personal_translations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("target_language_code", sa.String(length=8), nullable=False),
        sa.Column("translation_text", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personal_translations_item", "personal_translations",
        ["owner_user_id", "item_kind", "item_id"],
    )
    op.create_index(
        "uq_personal_translations_primary", "personal_translations",
        ["owner_user_id", "item_kind", "item_id", "target_language_code"],
        unique=True, postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "personal_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "item_kind", "item_id", name="uq_personal_notes_item"),
    )

    op.create_table(
        "item_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("tag_name", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "item_kind", "item_id", "tag_name", name="uq_item_tags"),
    )


def downgrade() -> None:
    op.drop_table("item_tags")
    op.drop_table("personal_notes")
    op.drop_index("uq_personal_translations_primary", table_name="personal_translations")
    op.drop_index("ix_personal_translations_item", table_name="personal_translations")
    op.drop_table("personal_translations")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_service.py::test_annotation_tables_roundtrip -v`
Expected: PASS (conftest `_init_schema` calls `Base.metadata.create_all`, which picks up the new models because `vocabulary.models` is already imported there).

- [ ] **Step 6: Verify the migration applies against a real DB**

Run: `cd backend && FLINQ_DATABASE_URL="postgresql+asyncpg://flinq:flinq@localhost:5433/flinq" uv run alembic upgrade head`
Expected: `Running upgrade 0006_reader_state -> 0007_vocabulary_card`.

- [ ] **Step 7: Commit**

```bash
cd /Users/shibaev/Dev/github/Flinq
git add backend/src/flinq/modules/vocabulary/models.py backend/migrations/versions/0007_vocabulary_card.py backend/tests/modules/test_vocabulary_service.py
git commit -m "feat(FLQ-5): vocabulary annotation tables (translations/notes/tags)"
```

---

## Task 2: Backend service — item state machine + lookup

**Files:**
- Create: `backend/src/flinq/modules/vocabulary/service.py`
- Test: `backend/tests/modules/test_vocabulary_service.py` (extend)

**Interfaces:**
- Consumes: `TokenItem`, `PersonalTranslation`, `PersonalNote`, `ItemTag` (Task 1); `normalize_token`.
- Produces:
  - `class ItemNotFound(Exception)`, `class UnsupportedKind(Exception)`
  - `async def create_item(session, *, user_id, kind, language_code, text, status, confidence) -> TokenItem`
  - `async def patch_item(session, *, user_id, kind, item_id, status, confidence) -> TokenItem`
  - `async def lookup(session, *, user_id, language_code, text, target_language_code) -> LookupResult`
  - `@dataclass class LookupResult` with fields `item_id: uuid.UUID | None`, `status: str`, `confidence: int | None`, `translations: list[PersonalTranslation]`, `primary: PersonalTranslation | None`, `note: str | None`, `tags: list[str]`.

- [ ] **Step 1: Write failing tests** (append to `test_vocabulary_service.py`)

```python
from flinq.modules.vocabulary import service


async def test_lookup_new_returns_new_status():
    async with session_scope() as s:
        user_id = await _make_user(s)
        res = await service.lookup(
            s, user_id=user_id, language_code="pt", text="Cada", target_language_code="ru",
        )
    assert res.item_id is None
    assert res.status == "new"
    assert res.confidence is None
    assert res.translations == []


async def test_create_item_tracked_then_patch_to_known():
    async with session_scope() as s:
        user_id = await _make_user(s)
    async with session_scope() as s:
        item = await service.create_item(
            s, user_id=user_id, kind="token", language_code="pt", text="cada",
            status="tracked", confidence=0,
        )
        item_id = item.id
    async with session_scope() as s:
        res = await service.lookup(
            s, user_id=user_id, language_code="pt", text="cada", target_language_code="ru",
        )
        assert res.status == "tracked" and res.confidence == 0
        patched = await service.patch_item(
            s, user_id=user_id, kind="token", item_id=item_id, status="known", confidence=None,
        )
        assert patched.status == "known" and patched.confidence is None


async def test_create_item_is_idempotent_on_unique():
    async with session_scope() as s:
        user_id = await _make_user(s)
    async with session_scope() as s:
        a = await service.create_item(
            s, user_id=user_id, kind="token", language_code="pt", text="cada",
            status="tracked", confidence=0,
        )
    async with session_scope() as s:
        b = await service.create_item(
            s, user_id=user_id, kind="token", language_code="pt", text="cada",
            status="ignored", confidence=None,
        )
    assert a.id == b.id and b.status == "ignored"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'flinq.modules.vocabulary.service'`.

- [ ] **Step 3: Implement `service.py`**

Create `backend/src/flinq/modules/vocabulary/service.py`:

```python
"""Vocabulary WordCard service (FLQ-5). Session-first module functions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.textnorm import normalize_token
from flinq.modules.vocabulary.models import ItemTag, PersonalNote, PersonalTranslation, TokenItem


class UnsupportedKind(Exception):
    """Only 'token' is supported in Increment 1."""


class ItemNotFound(Exception):
    """Item does not exist or is not owned by the user."""


@dataclass
class LookupResult:
    item_id: uuid.UUID | None
    status: str
    confidence: int | None
    translations: list[PersonalTranslation]
    primary: PersonalTranslation | None
    note: str | None
    tags: list[str] = field(default_factory=list)


def _check_kind(kind: str) -> None:
    if kind != "token":
        raise UnsupportedKind(kind)


async def _get_token_item(
    session: AsyncSession, *, user_id: uuid.UUID, language_code: str, text: str
) -> TokenItem | None:
    stmt = select(TokenItem).where(
        TokenItem.user_id == user_id,
        TokenItem.language_code == language_code,
        TokenItem.token_text == text,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _owned_item(
    session: AsyncSession, *, user_id: uuid.UUID, item_id: uuid.UUID
) -> TokenItem:
    item = await session.get(TokenItem, item_id)
    if item is None or item.user_id != user_id:
        raise ItemNotFound(str(item_id))
    return item


async def create_item(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, language_code: str,
    text: str, status: str, confidence: int | None,
) -> TokenItem:
    _check_kind(kind)
    normalized = normalize_token(text)
    existing = await _get_token_item(
        session, user_id=user_id, language_code=language_code, text=normalized
    )
    if existing is not None:
        existing.status = status
        existing.confidence = confidence
        await session.commit()
        return existing
    item = TokenItem(
        user_id=user_id, language_code=language_code, token_text=normalized,
        status=status, confidence=confidence,
    )
    session.add(item)
    await session.commit()
    return item


async def patch_item(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID,
    status: str, confidence: int | None,
) -> TokenItem:
    _check_kind(kind)
    item = await _owned_item(session, user_id=user_id, item_id=item_id)
    item.status = status
    item.confidence = confidence
    await session.commit()
    return item


async def lookup(
    session: AsyncSession, *, user_id: uuid.UUID, language_code: str, text: str,
    target_language_code: str,
) -> LookupResult:
    normalized = normalize_token(text)
    item = await _get_token_item(
        session, user_id=user_id, language_code=language_code, text=normalized
    )
    if item is None:
        return LookupResult(
            item_id=None, status="new", confidence=None,
            translations=[], primary=None, note=None, tags=[],
        )
    translations = list(
        (await session.execute(
            select(PersonalTranslation)
            .where(
                PersonalTranslation.owner_user_id == user_id,
                PersonalTranslation.item_kind == "token",
                PersonalTranslation.item_id == item.id,
            )
            .order_by(PersonalTranslation.is_primary.desc(), PersonalTranslation.created_at)
        )).scalars().all()
    )
    primary = next(
        (t for t in translations
         if t.is_primary and t.target_language_code == target_language_code),
        None,
    )
    note_row = (await session.execute(
        select(PersonalNote).where(
            PersonalNote.owner_user_id == user_id,
            PersonalNote.item_kind == "token",
            PersonalNote.item_id == item.id,
        )
    )).scalar_one_or_none()
    tags = list(
        (await session.execute(
            select(ItemTag.tag_name).where(
                ItemTag.owner_user_id == user_id,
                ItemTag.item_kind == "token",
                ItemTag.item_id == item.id,
            ).order_by(ItemTag.tag_name)
        )).scalars().all()
    )
    return LookupResult(
        item_id=item.id, status=item.status, confidence=item.confidence,
        translations=translations, primary=primary,
        note=note_row.note_text if note_row else None, tags=tags,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_service.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/flinq/modules/vocabulary/service.py backend/tests/modules/test_vocabulary_service.py
git commit -m "feat(FLQ-5): vocabulary service — item state machine + lookup"
```

---

## Task 3: Backend service — translations, notes, tags

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/service.py`
- Test: `backend/tests/modules/test_vocabulary_service.py` (extend)

**Interfaces:**
- Consumes: `_owned_item`, `_check_kind` (Task 2).
- Produces:
  - `async def add_translation(session, *, user_id, kind, item_id, target_language_code, translation_text, is_primary, source_type) -> PersonalTranslation`
  - `async def put_note(session, *, user_id, kind, item_id, note_text) -> PersonalNote`
  - `async def add_tag(session, *, user_id, kind, item_id, tag_name) -> list[str]`
  - `async def remove_tag(session, *, user_id, kind, item_id, tag_name) -> list[str]`

- [ ] **Step 1: Write failing tests** (append)

```python
async def _tracked_item(user_id) -> uuid.UUID:
    async with session_scope() as s:
        item = await service.create_item(
            s, user_id=user_id, kind="token", language_code="pt", text="cada",
            status="tracked", confidence=0,
        )
        return item.id


async def test_add_translation_promotes_single_primary():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        await service.add_translation(
            s, user_id=user_id, kind="token", item_id=item_id,
            target_language_code="ru", translation_text="первый", is_primary=True,
            source_type="user",
        )
    async with session_scope() as s:
        await service.add_translation(
            s, user_id=user_id, kind="token", item_id=item_id,
            target_language_code="ru", translation_text="второй", is_primary=True,
            source_type="user",
        )
    async with session_scope() as s:
        res = await service.lookup(
            s, user_id=user_id, language_code="pt", text="cada", target_language_code="ru",
        )
    assert res.primary is not None and res.primary.translation_text == "второй"
    assert sum(1 for t in res.translations if t.is_primary) == 1


async def test_put_note_upserts():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        await service.put_note(s, user_id=user_id, kind="token", item_id=item_id, note_text="a")
    async with session_scope() as s:
        await service.put_note(s, user_id=user_id, kind="token", item_id=item_id, note_text="b")
    async with session_scope() as s:
        res = await service.lookup(
            s, user_id=user_id, language_code="pt", text="cada", target_language_code="ru",
        )
    assert res.note == "b"


async def test_add_and_remove_tag():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        tags = await service.add_tag(s, user_id=user_id, kind="token", item_id=item_id, tag_name="verbs")
        assert tags == ["verbs"]
        # idempotent
        tags = await service.add_tag(s, user_id=user_id, kind="token", item_id=item_id, tag_name="verbs")
        assert tags == ["verbs"]
    async with session_scope() as s:
        tags = await service.remove_tag(s, user_id=user_id, kind="token", item_id=item_id, tag_name="verbs")
        assert tags == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_service.py -k "translation or note or tag" -v`
Expected: FAIL — `AttributeError: module 'flinq.modules.vocabulary.service' has no attribute 'add_translation'`.

- [ ] **Step 3: Implement the functions** (append to `service.py`; add imports `from sqlalchemy import delete, update` and `from sqlalchemy.dialects.postgresql import insert as pg_insert`)

```python
async def _list_tags(session: AsyncSession, *, user_id: uuid.UUID, item_id: uuid.UUID) -> list[str]:
    return list(
        (await session.execute(
            select(ItemTag.tag_name).where(
                ItemTag.owner_user_id == user_id,
                ItemTag.item_kind == "token",
                ItemTag.item_id == item_id,
            ).order_by(ItemTag.tag_name)
        )).scalars().all()
    )


async def add_translation(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID,
    target_language_code: str, translation_text: str, is_primary: bool, source_type: str,
) -> PersonalTranslation:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    if is_primary:
        await session.execute(
            update(PersonalTranslation)
            .where(
                PersonalTranslation.owner_user_id == user_id,
                PersonalTranslation.item_kind == "token",
                PersonalTranslation.item_id == item_id,
                PersonalTranslation.target_language_code == target_language_code,
                PersonalTranslation.is_primary.is_(True),
            )
            .values(is_primary=False)
        )
    row = PersonalTranslation(
        owner_user_id=user_id, item_kind="token", item_id=item_id,
        target_language_code=target_language_code, translation_text=translation_text,
        is_primary=is_primary, source_type=source_type,
    )
    session.add(row)
    await session.commit()
    return row


async def put_note(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID, note_text: str,
) -> PersonalNote:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    stmt = (
        pg_insert(PersonalNote)
        .values(
            id=uuid.uuid4(), owner_user_id=user_id, item_kind="token",
            item_id=item_id, note_text=note_text,
        )
        .on_conflict_do_update(
            constraint="uq_personal_notes_item", set_={"note_text": note_text}
        )
        .returning(PersonalNote)
    )
    row = (await session.execute(stmt)).scalar_one()
    await session.commit()
    return row


async def add_tag(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID, tag_name: str,
) -> list[str]:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    await session.execute(
        pg_insert(ItemTag)
        .values(
            id=uuid.uuid4(), owner_user_id=user_id, item_kind="token",
            item_id=item_id, tag_name=tag_name,
        )
        .on_conflict_do_nothing(constraint="uq_item_tags")
    )
    await session.commit()
    return await _list_tags(session, user_id=user_id, item_id=item_id)


async def remove_tag(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID, tag_name: str,
) -> list[str]:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    await session.execute(
        delete(ItemTag).where(
            ItemTag.owner_user_id == user_id,
            ItemTag.item_kind == "token",
            ItemTag.item_id == item_id,
            ItemTag.tag_name == tag_name,
        )
    )
    await session.commit()
    return await _list_tags(session, user_id=user_id, item_id=item_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_service.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/flinq/modules/vocabulary/service.py backend/tests/modules/test_vocabulary_service.py
git commit -m "feat(FLQ-5): vocabulary service — translations, notes, tags"
```

---

## Task 4: Backend API — /api/vocabulary router

**Files:**
- Create: `backend/src/flinq/modules/vocabulary/schemas.py`
- Create: `backend/src/flinq/api/vocabulary.py`
- Modify: `backend/src/flinq/main.py`
- Test: `backend/tests/api/test_vocabulary.py`

**Interfaces:**
- Consumes: all `service` functions (Tasks 2-3).
- Produces: router at `prefix="/api/vocabulary"` with `GET /lookup`, `POST /items`, `PATCH /items/{kind}/{item_id}`, `POST /items/{kind}/{item_id}/translations`, `PUT /items/{kind}/{item_id}/notes`, `POST /items/{kind}/{item_id}/tags`, `DELETE /items/{kind}/{item_id}/tags/{tag_name}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/test_vocabulary.py`:

```python
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from flinq.core.db import session_scope
from flinq.main import create_app
from flinq.modules.vocabulary.models import ItemTag, PersonalNote, PersonalTranslation, TokenItem


@pytest.fixture(autouse=True)
async def _clean():
    yield
    async with session_scope() as s:
        for model in (PersonalTranslation, PersonalNote, ItemTag, TokenItem):
            await s.execute(model.__table__.delete())


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def _register(c: AsyncClient) -> str:
    r = await c.post("/auth/register", json={
        "display_name": "T", "email": f"{uuid.uuid4().hex}@t.io", "password": "abcdefghij",
    })
    assert r.status_code == 201
    csrf = c.cookies.get("flinq_csrf")
    assert csrf
    return csrf


async def test_lookup_new_word():
    async with await _client() as c:
        await _register(c)
        r = await c.get("/api/vocabulary/lookup", params={"lang": "pt", "text": "Cada", "target": "ru"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "new" and body["item_id"] is None


async def test_create_then_translate_then_lookup():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        r = await c.post("/api/vocabulary/items", headers=h, json={
            "kind": "token", "language_code": "pt", "text": "cada",
            "status": "tracked", "confidence": 0,
        })
        assert r.status_code == 201
        item_id = r.json()["item_id"]
        r = await c.post(f"/api/vocabulary/items/token/{item_id}/translations", headers=h, json={
            "target_language_code": "ru", "translation_text": "каждый",
            "is_primary": True, "source_type": "user",
        })
        assert r.status_code == 201
        r = await c.get("/api/vocabulary/lookup", params={"lang": "pt", "text": "cada", "target": "ru"})
        body = r.json()
        assert body["status"] == "tracked" and body["confidence"] == 0
        assert body["translations"]["primary"]["text"] == "каждый"


async def test_patch_tags_notes():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        item_id = (await c.post("/api/vocabulary/items", headers=h, json={
            "kind": "token", "language_code": "pt", "text": "cada",
            "status": "tracked", "confidence": 0,
        })).json()["item_id"]
        r = await c.patch(f"/api/vocabulary/items/token/{item_id}", headers=h,
                          json={"status": "known", "confidence": None})
        assert r.status_code == 200 and r.json()["status"] == "known"
        r = await c.post(f"/api/vocabulary/items/token/{item_id}/tags", headers=h,
                         json={"tag_name": "verbs"})
        assert r.status_code == 200 and r.json()["tags"] == ["verbs"]
        r = await c.put(f"/api/vocabulary/items/token/{item_id}/notes", headers=h,
                        json={"note_text": "hello"})
        assert r.status_code == 200 and r.json()["note"] == "hello"


async def test_lookup_requires_auth():
    async with await _client() as c:
        r = await c.get("/api/vocabulary/lookup", params={"lang": "pt", "text": "x", "target": "ru"})
        assert r.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_vocabulary.py -v`
Expected: FAIL — 404 on `/api/vocabulary/lookup` (router not registered).

- [ ] **Step 3: Write `schemas.py`**

Create `backend/src/flinq/modules/vocabulary/schemas.py`:

```python
"""Pydantic DTOs for the vocabulary WordCard API (FLQ-5)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

LangCode = Literal["en", "ru", "pt"]
ItemStatus = Literal["tracked", "known", "ignored"]


class TranslationOut(BaseModel):
    id: uuid.UUID
    text: str
    target_language_code: str
    is_primary: bool
    source_type: str


class TranslationsBlock(BaseModel):
    primary: TranslationOut | None
    all: list[TranslationOut]


class LookupResponse(BaseModel):
    item_id: uuid.UUID | None
    status: Literal["new", "tracked", "known", "ignored"]
    confidence: int | None
    translations: TranslationsBlock
    note: str | None
    tags: list[str]


class CreateItemRequest(BaseModel):
    kind: Literal["token"] = "token"
    language_code: LangCode
    text: str = Field(min_length=1, max_length=256)
    status: ItemStatus
    confidence: int | None = Field(default=None, ge=0, le=5)

    @model_validator(mode="after")
    def _confidence_matches_status(self) -> "CreateItemRequest":
        if (self.status == "tracked") != (self.confidence is not None):
            raise ValueError("confidence required iff status == 'tracked'")
        return self


class PatchItemRequest(BaseModel):
    status: ItemStatus
    confidence: int | None = Field(default=None, ge=0, le=5)

    @model_validator(mode="after")
    def _confidence_matches_status(self) -> "PatchItemRequest":
        if (self.status == "tracked") != (self.confidence is not None):
            raise ValueError("confidence required iff status == 'tracked'")
        return self


class ItemStateResponse(BaseModel):
    item_id: uuid.UUID
    status: str
    confidence: int | None


class AddTranslationRequest(BaseModel):
    target_language_code: LangCode
    translation_text: str = Field(min_length=1, max_length=512)
    is_primary: bool = True
    source_type: Literal["user", "ai", "dictionary"] = "user"


class PutNoteRequest(BaseModel):
    note_text: str = Field(max_length=4000)


class NoteResponse(BaseModel):
    note: str


class AddTagRequest(BaseModel):
    tag_name: str = Field(min_length=1, max_length=64)


class TagsResponse(BaseModel):
    tags: list[str]
```

- [ ] **Step 4: Write the router**

Create `backend/src/flinq/api/vocabulary.py`:

```python
"""Vocabulary WordCard API (FLQ-5)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.vocabulary import service
from flinq.modules.vocabulary.schemas import (
    AddTagRequest,
    AddTranslationRequest,
    CreateItemRequest,
    ItemStateResponse,
    LookupResponse,
    NoteResponse,
    PatchItemRequest,
    PutNoteRequest,
    TagsResponse,
    TranslationOut,
    TranslationsBlock,
)

router = APIRouter(prefix="/api/vocabulary", tags=["vocabulary"])

LangCode = Literal["en", "ru", "pt"]
Kind = Literal["token", "phrase"]


def _require_user(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user_id


def _translation_out(t) -> TranslationOut:
    return TranslationOut(
        id=t.id, text=t.translation_text, target_language_code=t.target_language_code,
        is_primary=t.is_primary, source_type=t.source_type,
    )


def _map_service_errors(fn):
    # helper: convert UnsupportedKind -> 400, ItemNotFound -> 404
    ...


@router.get("/lookup", response_model=LookupResponse)
async def lookup(
    request: Request,
    lang: LangCode,
    text: Annotated[str, Query(min_length=1, max_length=256)],
    target: LangCode,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LookupResponse:
    user_id = _require_user(request)
    res = await service.lookup(
        session, user_id=user_id, language_code=lang, text=text, target_language_code=target,
    )
    return LookupResponse(
        item_id=res.item_id,
        status=res.status,
        confidence=res.confidence,
        translations=TranslationsBlock(
            primary=_translation_out(res.primary) if res.primary else None,
            all=[_translation_out(t) for t in res.translations],
        ),
        note=res.note,
        tags=res.tags,
    )


@router.post("/items", status_code=201, response_model=ItemStateResponse)
async def create_item(
    request: Request,
    body: CreateItemRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ItemStateResponse:
    user_id = _require_user(request)
    item = await service.create_item(
        session, user_id=user_id, kind=body.kind, language_code=body.language_code,
        text=body.text, status=body.status, confidence=body.confidence,
    )
    return ItemStateResponse(item_id=item.id, status=item.status, confidence=item.confidence)


def _resolve(kind: str, item_id: uuid.UUID) -> None:
    if kind != "token":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unsupported item kind")


@router.patch("/items/{kind}/{item_id}", response_model=ItemStateResponse)
async def patch_item(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    body: PatchItemRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ItemStateResponse:
    user_id = _require_user(request)
    _resolve(kind, item_id)
    try:
        item = await service.patch_item(
            session, user_id=user_id, kind=kind, item_id=item_id,
            status=body.status, confidence=body.confidence,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return ItemStateResponse(item_id=item.id, status=item.status, confidence=item.confidence)


@router.post("/items/{kind}/{item_id}/translations", status_code=201, response_model=TranslationOut)
async def add_translation(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    body: AddTranslationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranslationOut:
    user_id = _require_user(request)
    _resolve(kind, item_id)
    try:
        row = await service.add_translation(
            session, user_id=user_id, kind=kind, item_id=item_id,
            target_language_code=body.target_language_code, translation_text=body.translation_text,
            is_primary=body.is_primary, source_type=body.source_type,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return _translation_out(row)


@router.put("/items/{kind}/{item_id}/notes", response_model=NoteResponse)
async def put_note(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    body: PutNoteRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NoteResponse:
    user_id = _require_user(request)
    _resolve(kind, item_id)
    try:
        row = await service.put_note(
            session, user_id=user_id, kind=kind, item_id=item_id, note_text=body.note_text,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return NoteResponse(note=row.note_text)


@router.post("/items/{kind}/{item_id}/tags", response_model=TagsResponse)
async def add_tag(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    body: AddTagRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TagsResponse:
    user_id = _require_user(request)
    _resolve(kind, item_id)
    try:
        tags = await service.add_tag(
            session, user_id=user_id, kind=kind, item_id=item_id, tag_name=body.tag_name,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return TagsResponse(tags=tags)


@router.delete("/items/{kind}/{item_id}/tags/{tag_name}", response_model=TagsResponse)
async def remove_tag(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    tag_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TagsResponse:
    user_id = _require_user(request)
    _resolve(kind, item_id)
    try:
        tags = await service.remove_tag(
            session, user_id=user_id, kind=kind, item_id=item_id, tag_name=tag_name,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return TagsResponse(tags=tags)
```

Note: remove the unused `_map_service_errors` stub — it is illustrative only; delete it before running. Each handler already maps `ItemNotFound → 404` inline.

- [ ] **Step 5: Register the router in `main.py`**

Add import next to the other router imports (`main.py:17-23`):
```python
from flinq.api.vocabulary import router as vocabulary_router
```
Add inside `create_app` after `app.include_router(dictionary_router)` (`main.py:68`):
```python
app.include_router(vocabulary_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/test_vocabulary.py -v`
Expected: PASS (4 tests). If `test_lookup_requires_auth` returns 403 instead of 401, that is a GET (non-mutating) so CSRF does not fire — it must be 401; confirm `_require_user` runs.

- [ ] **Step 7: Typecheck + full backend suite**

Run: `cd backend && uv run pyright src/flinq/modules/vocabulary src/flinq/api/vocabulary.py && uv run pytest tests/modules/test_vocabulary_service.py tests/api/test_vocabulary.py -q`
Expected: no type errors; all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/src/flinq/modules/vocabulary/schemas.py backend/src/flinq/api/vocabulary.py backend/src/flinq/main.py backend/tests/api/test_vocabulary.py
git commit -m "feat(FLQ-5): /api/vocabulary router (lookup/items/translations/notes/tags)"
```

---

## Task 5: Frontend API modules + hooks

**Files:**
- Create: `frontend/src/api/vocabulary.ts`
- Create: `frontend/src/api/dictionary.ts`
- Create: `frontend/src/features/reader/useWordCard.ts`

**Interfaces:**
- Produces: `vocabularyApi` (lookup/createItem/patchItem/addTranslation/putNote/addTag/removeTag) + types `WordLookup`, `ItemKind`, `ItemStatus`; `dictionaryApi.lookup`; hooks `useWordLookup`, `useWordCardMutations`.

- [ ] **Step 1: Create `src/api/vocabulary.ts`**

```ts
import { api } from './client'

export type ItemKind = 'token' | 'phrase'
export type CardStatus = 'new' | 'tracked' | 'known' | 'ignored'
export type WriteStatus = 'tracked' | 'known' | 'ignored'
export type SourceType = 'user' | 'ai' | 'dictionary'

export interface TranslationOut {
  id: string
  text: string
  target_language_code: string
  is_primary: boolean
  source_type: SourceType
}

export interface WordLookup {
  item_id: string | null
  status: CardStatus
  confidence: number | null
  translations: { primary: TranslationOut | null; all: TranslationOut[] }
  note: string | null
  tags: string[]
}

export interface ItemState {
  item_id: string
  status: string
  confidence: number | null
}

export const vocabularyApi = {
  lookup: (lang: string, text: string, target: string) => {
    const q = new URLSearchParams({ lang, text, target })
    return api<WordLookup>(`/api/vocabulary/lookup?${q.toString()}`)
  },
  createItem: (body: {
    kind: 'token'; language_code: string; text: string
    status: WriteStatus; confidence: number | null
  }) => api<ItemState>('/api/vocabulary/items', { method: 'POST', body: JSON.stringify(body) }),
  patchItem: (kind: ItemKind, id: string, body: { status: WriteStatus; confidence: number | null }) =>
    api<ItemState>(`/api/vocabulary/items/${kind}/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  addTranslation: (kind: ItemKind, id: string, body: {
    target_language_code: string; translation_text: string
    is_primary?: boolean; source_type?: SourceType
  }) => api<TranslationOut>(`/api/vocabulary/items/${kind}/${id}/translations`, {
    method: 'POST', body: JSON.stringify(body),
  }),
  putNote: (kind: ItemKind, id: string, note_text: string) =>
    api<{ note: string }>(`/api/vocabulary/items/${kind}/${id}/notes`, {
      method: 'PUT', body: JSON.stringify({ note_text }),
    }),
  addTag: (kind: ItemKind, id: string, tag_name: string) =>
    api<{ tags: string[] }>(`/api/vocabulary/items/${kind}/${id}/tags`, {
      method: 'POST', body: JSON.stringify({ tag_name }),
    }),
  removeTag: (kind: ItemKind, id: string, tag: string) =>
    api<{ tags: string[] }>(`/api/vocabulary/items/${kind}/${id}/tags/${encodeURIComponent(tag)}`, {
      method: 'DELETE',
    }),
}
```

- [ ] **Step 2: Create `src/api/dictionary.ts`** (matches backend `DictionaryLookupResponse`)

```ts
import { api } from './client'

export interface DictionarySense {
  sense_index: number
  translation: string
  usage_note: string | null
  examples: { text: string; translation: string | null }[]
}
export interface DictionaryEntry {
  headword: string
  part_of_speech: string | null
  senses: DictionarySense[]
}
export interface DictionaryLookup {
  entries: DictionaryEntry[]
  attribution: { source: string; license: string; url: string }
  external_links: { name: string; url: string }[]
}

export const dictionaryApi = {
  lookup: (lang: string, target: string, text: string) => {
    const q = new URLSearchParams({ lang, target, text })
    return api<DictionaryLookup>(`/api/dictionary/lookup?${q.toString()}`)
  },
}
```

- [ ] **Step 3: Create `src/features/reader/useWordCard.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { vocabularyApi } from '@/api/vocabulary'
import type { ItemKind, WriteStatus } from '@/api/vocabulary'

export function wordLookupKey(lang: string, text: string, target: string) {
  return ['word-card', lang, text, target] as const
}

export function useWordLookup(lang: string, text: string | null, target: string) {
  return useQuery({
    queryKey: wordLookupKey(lang, text ?? '', target),
    queryFn: () => vocabularyApi.lookup(lang, text as string, target),
    enabled: text !== null,
  })
}

/**
 * Mutations for the open card. `invalidate()` refreshes both the card lookup
 * and the reader token statuses so highlight colours update.
 */
export function useWordCardMutations(opts: {
  lang: string
  text: string
  target: string
  lessonId: string
}) {
  const qc = useQueryClient()
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: wordLookupKey(opts.lang, opts.text, opts.target) })
    void qc.invalidateQueries({ queryKey: ['reader-statuses', opts.lessonId] })
  }

  const setStatus = useMutation({
    // For a new word (no id) pass itemId=null → create; else patch.
    mutationFn: (v: { itemId: string | null; status: WriteStatus; confidence: number | null }) =>
      v.itemId === null
        ? vocabularyApi.createItem({
            kind: 'token', language_code: opts.lang, text: opts.text,
            status: v.status, confidence: v.confidence,
          })
        : vocabularyApi.patchItem('token', v.itemId, { status: v.status, confidence: v.confidence }),
    onSuccess: invalidate,
  })

  const saveTranslation = useMutation({
    mutationFn: (v: { itemId: string; text: string; source?: 'user' | 'ai' | 'dictionary' }) =>
      vocabularyApi.addTranslation('token' as ItemKind, v.itemId, {
        target_language_code: opts.target, translation_text: v.text,
        is_primary: true, source_type: v.source ?? 'user',
      }),
    onSuccess: invalidate,
  })

  const saveNote = useMutation({
    mutationFn: (v: { itemId: string; note: string }) =>
      vocabularyApi.putNote('token', v.itemId, v.note),
    onSuccess: invalidate,
  })

  const addTag = useMutation({
    mutationFn: (v: { itemId: string; tag: string }) => vocabularyApi.addTag('token', v.itemId, v.tag),
    onSuccess: invalidate,
  })

  const removeTag = useMutation({
    mutationFn: (v: { itemId: string; tag: string }) => vocabularyApi.removeTag('token', v.itemId, v.tag),
    onSuccess: invalidate,
  })

  return { setStatus, saveTranslation, saveNote, addTag, removeTag }
}
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && corepack pnpm exec tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/vocabulary.ts frontend/src/api/dictionary.ts frontend/src/features/reader/useWordCard.ts
git commit -m "feat(FLQ-5): frontend vocabulary API + word-card query hooks"
```

---

## Task 6: Reader highlight — (status, confidence)-aware TokenSpan

**Files:**
- Modify: `frontend/src/features/reader/TokenSpan.tsx`
- Test: `frontend/src/features/reader/TokenSpan.test.tsx`

**Interfaces:**
- Consumes: `TokenStatusEntry` (`{ s, c? }`) from `@/api/reader` (unchanged).
- Produces: background rule — `tracked && (c ?? 0) >= 1` → tracked-bg; `new` OR `tracked && c falsy/0` → new-bg; `known`/`ignored` → none.

- [ ] **Step 1: Add failing test cases** to `TokenSpan.test.tsx`

```tsx
it('renders a tracked word with confidence 0 as new (blue), not yellow', () => {
  render(<TokenSpan token={{ t: 'Hola', n: 'hola', i: 3 }} status={{ s: 'tracked', c: 0 }} />)
  const el = screen.getByText('Hola')
  expect(el.className).toContain('bg-[var(--reader-new-bg)]')
  expect(el.className).not.toContain('bg-[var(--reader-tracked-bg)]')
})

it('renders a tracked word with confidence >= 1 as tracked (yellow)', () => {
  render(<TokenSpan token={{ t: 'Hola', n: 'hola', i: 3 }} status={{ s: 'tracked', c: 2 }} />)
  expect(screen.getByText('Hola').className).toContain('bg-[var(--reader-tracked-bg)]')
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && corepack pnpm exec vitest run src/features/reader/TokenSpan.test.tsx`
Expected: FAIL — the confidence-0 case currently gets `bg-[var(--reader-tracked-bg)]`.

- [ ] **Step 3: Update the background logic in `TokenSpan.tsx`**

Replace the `const bg = ...` expression with:

```tsx
  const s = status?.s
  const active = s === 'tracked' && (status?.c ?? 0) >= 1
  const bg = active
    ? 'bg-[var(--reader-tracked-bg)]'
    : s === 'known' || s === 'ignored'
      ? ''
      : 'bg-[var(--reader-new-bg)]'
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && corepack pnpm exec vitest run src/features/reader/TokenSpan.test.tsx`
Expected: PASS (all cases, including pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/reader/TokenSpan.tsx frontend/src/features/reader/TokenSpan.test.tsx
git commit -m "feat(FLQ-5): reader highlight is confidence-aware (tracked-0 stays blue)"
```

---

## Task 7: WordCard component — core (header, translation, footer, collapse)

**Files:**
- Create: `frontend/src/features/reader/WordCard.tsx`
- Create: `frontend/src/features/reader/WordCard.test.tsx`

**Interfaces:**
- Consumes: `useWordLookup`, `useWordCardMutations` (Task 5).
- Produces: `export function WordCard(props: { word: {t;n;i}|null; lang: string; target: string; lessonId: string; onClose: () => void })`. Keeps the placeholder's mobile-sheet/`md:`-sidebar layout and `data-testid`s (`word-card-backdrop`, plus new `word-card`). Debounced (800ms) translation save; footer `🗑 [1][2][3][4] ✓`; collapse/expand via chevron.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/reader/WordCard.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/vocabulary', () => ({
  vocabularyApi: {
    lookup: vi.fn(), createItem: vi.fn(), patchItem: vi.fn(),
    addTranslation: vi.fn(), putNote: vi.fn(), addTag: vi.fn(), removeTag: vi.fn(),
  },
}))
vi.mock('@/api/dictionary', () => ({ dictionaryApi: { lookup: vi.fn() } }))
vi.mock('@/api/ai', () => ({ aiApi: { translate: vi.fn() } }))

import { vocabularyApi } from '@/api/vocabulary'
import { dictionaryApi } from '@/api/dictionary'
import { WordCard } from './WordCard'

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <WordCard
        word={{ t: 'cada', n: 'cada', i: 0 }}
        lang="pt" target="ru" lessonId="L1" onClose={() => {}}
      />
    </QueryClientProvider>,
  )
}

describe('WordCard core', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(dictionaryApi.lookup).mockResolvedValue({ entries: [], attribution: { source: '', license: '', url: '' }, external_links: [] })
  })

  it('creates a tracked/0 item when a translation is typed on a new word', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(vocabularyApi.createItem).mockResolvedValue({ item_id: 'I1', status: 'tracked', confidence: 0 })
    vi.mocked(vocabularyApi.addTranslation).mockResolvedValue({ id: 'T1', text: 'каждый', target_language_code: 'ru', is_primary: true, source_type: 'user' })

    renderCard()
    const input = await screen.findByPlaceholderText('Введите новый перевод здесь')
    fireEvent.change(input, { target: { value: 'каждый' } })
    fireEvent.blur(input)

    await waitFor(() => {
      expect(vocabularyApi.createItem).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'tracked', confidence: 0, text: 'cada' }),
      )
    })
    await waitFor(() => {
      expect(vocabularyApi.addTranslation).toHaveBeenCalledWith(
        'token', 'I1', expect.objectContaining({ translation_text: 'каждый' }),
      )
    })
  })

  it('sets confidence via the footer pill on an existing tracked item', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'tracked', confidence: 0,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(vocabularyApi.patchItem).mockResolvedValue({ item_id: 'I1', status: 'tracked', confidence: 2 })

    renderCard()
    const pill = await screen.findByRole('button', { name: 'Уровень 2' })
    fireEvent.click(pill)
    await waitFor(() => {
      expect(vocabularyApi.patchItem).toHaveBeenCalledWith('token', 'I1', { status: 'tracked', confidence: 2 })
    })
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && corepack pnpm exec vitest run src/features/reader/WordCard.test.tsx`
Expected: FAIL — `WordCard` not found.

- [ ] **Step 3: Implement `WordCard.tsx`** (core; suggestions/tags/notes added in Task 8 — write the full file now with those regions present but minimal)

```tsx
import { useEffect, useRef, useState } from 'react'
import { X, ChevronDown, ChevronUp, Check, Trash2 } from 'lucide-react'

import { useWordLookup, useWordCardMutations } from './useWordCard'

interface SelectedWord {
  t: string
  n: string
  i: number
}

interface Props {
  word: SelectedWord | null
  lang: string
  target: string
  lessonId: string
  onClose: () => void
}

const PILLS = [1, 2, 3, 4] as const

export function WordCard({ word, lang, target, lessonId, onClose }: Props) {
  const [expanded, setExpanded] = useState(false)
  const text = word?.n ?? null
  const lookup = useWordLookup(lang, text, target)
  const m = useWordCardMutations({ lang, text: text ?? '', target, lessonId })

  const data = lookup.data
  const itemId = data?.item_id ?? null
  const status = data?.status ?? 'new'
  const confidence = data?.confidence ?? null

  // translation input (debounced)
  const [draft, setDraft] = useState('')
  const savedRef = useRef<string>('')
  useEffect(() => {
    const primary = data?.translations.primary?.text ?? ''
    setDraft(primary)
    savedRef.current = primary
  }, [data?.item_id, data?.translations.primary?.text])

  useEffect(() => {
    if (!word) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (data && /^[1-4]$/.test(e.key)) applyStatus('tracked', Number(e.key))
      if (data && e.key === 'k') applyStatus('known', null)
      if (data && e.key === 'i') applyStatus('ignored', null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [word, data])

  if (!word) return null

  async function ensureItem(nextStatus: 'tracked' | 'known' | 'ignored', conf: number | null) {
    const res = await m.setStatus.mutateAsync({ itemId, status: nextStatus, confidence: conf })
    return res.item_id
  }

  function applyStatus(nextStatus: 'tracked' | 'known' | 'ignored', conf: number | null) {
    void m.setStatus.mutate({ itemId, status: nextStatus, confidence: conf })
  }

  async function saveTranslation() {
    const value = draft.trim()
    if (!value || value === savedRef.current) return
    savedRef.current = value
    // new word: create tracked/0 first, then translate
    const id = itemId ?? (await ensureItem('tracked', 0))
    await m.saveTranslation.mutateAsync({ itemId: id, text: value, source: 'user' })
  }

  return (
    <>
      <div
        data-testid="word-card-backdrop"
        className="fixed inset-0 z-[var(--z-modal-backdrop)] bg-black/10 md:hidden"
        onClick={onClose}
      />
      <div
        data-testid="word-card"
        className="fixed inset-x-0 bottom-0 z-[var(--z-modal)] rounded-t-xl border border-border bg-card p-4 shadow-lg md:inset-x-auto md:right-0 md:top-0 md:h-full md:w-80 md:overflow-y-auto md:rounded-none md:border-y-0 md:border-r-0 md:border-l md:shadow-none"
      >
        <button
          type="button" aria-label="Закрыть" onClick={onClose}
          className="absolute right-3 top-3 rounded-md p-1 hover:bg-accent"
        >
          <X className="h-4 w-4" />
        </button>

        <p className="text-2xl font-semibold">{word.t}</p>

        {/* Saved translation */}
        <label className="mt-4 block text-sm font-medium">Сохранённый перевод</label>
        <input
          className="mt-1 w-full rounded-md border border-border px-3 py-2 text-base"
          placeholder="Введите новый перевод здесь"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void saveTranslation()}
          onKeyDown={(e) => { if (e.key === 'Enter') void saveTranslation() }}
        />

        {/* Suggestions region — filled in Task 8 */}
        <div data-testid="word-card-suggestions" className="mt-4" />

        {expanded && (
          <div data-testid="word-card-expanded" className="mt-4">
            {/* Tags + notes — filled in Task 8 */}
          </div>
        )}

        {/* Footer: 🗑 [1][2][3][4] ✓ */}
        <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
          <button
            type="button" aria-label="Игнорировать" title="Игнорировать"
            onClick={() => applyStatus('ignored', null)}
            className={`rounded-full border p-2 hover:bg-accent ${status === 'ignored' ? 'border-foreground' : 'border-border'}`}
          >
            <Trash2 className="h-4 w-4" />
          </button>
          <div className="flex items-center gap-1">
            {PILLS.map((n) => (
              <button
                key={n} type="button" aria-label={`Уровень ${n}`}
                onClick={() => applyStatus('tracked', n)}
                className={`flex h-8 w-8 items-center justify-center rounded-full border text-sm ${
                  status === 'tracked' && confidence === n
                    ? 'border-primary bg-primary/10 font-semibold'
                    : 'border-border hover:bg-accent'
                }`}
              >
                {n}
              </button>
            ))}
          </div>
          <button
            type="button" aria-label="Изучено" title="Изучено"
            onClick={() => applyStatus('known', null)}
            className={`rounded-full border p-2 hover:bg-accent ${status === 'known' ? 'border-primary bg-primary/10' : 'border-border'}`}
          >
            <Check className="h-4 w-4" />
          </button>
        </div>

        <button
          type="button"
          aria-label={expanded ? 'Свернуть' : 'Развернуть'}
          onClick={() => setExpanded((v) => !v)}
          className="mx-auto mt-2 flex rounded-md p-1 text-muted-foreground hover:bg-accent"
        >
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
      </div>
    </>
  )
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && corepack pnpm exec vitest run src/features/reader/WordCard.test.tsx`
Expected: PASS (both core tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/reader/WordCard.tsx frontend/src/features/reader/WordCard.test.tsx
git commit -m "feat(FLQ-5): WordCard core — translation input, confidence footer, hotkeys"
```

---

## Task 8: WordCard — suggestions (user/AI/Wiktionary), tags, notes

**Files:**
- Modify: `frontend/src/features/reader/WordCard.tsx`
- Create: `frontend/src/api/ai.ts` (thin wrapper for `/api/ai/translate`, if not already present — verify first)
- Test: `frontend/src/features/reader/WordCard.test.tsx` (extend)

**Interfaces:**
- Consumes: `dictionaryApi.lookup` (Task 5), `aiApi.translate` (this task), lookup translations (`data.translations.all`).
- Produces: a merged suggestion list (user-saved → AI(`✦`) → Wiktionary(`📘`)); each row has a `+` that saves it as primary; expanded region renders tags chip-input + notes textarea.

- [ ] **Step 1: Verify/create the AI api wrapper**

Check whether `frontend/src/api/ai.ts` exists. If not, create it (contract from `backend/src/flinq/api/ai.py`):

```ts
import { api } from './client'

export interface TranslateResponse {
  hints: { text: string }[]
  model: string
  latency_ms: number
}

export const aiApi = {
  translate: (body: {
    surface_text: string; context_text: string
    target_language_code: string; lesson_id?: string
  }) => api<TranslateResponse>('/api/ai/translate', { method: 'POST', body: JSON.stringify(body) }),
}
```

- [ ] **Step 2: Add failing tests** (append to `WordCard.test.tsx`)

```tsx
it('shows a Wiktionary suggestion and saves it as primary on +', async () => {
  vi.mocked(vocabularyApi.lookup).mockResolvedValue({
    item_id: 'I1', status: 'tracked', confidence: 1,
    translations: { primary: null, all: [] }, note: null, tags: [],
  })
  vi.mocked(dictionaryApi.lookup).mockResolvedValue({
    entries: [{ headword: 'cada', part_of_speech: 'det', senses: [
      { sense_index: 0, translation: 'каждый', usage_note: null, examples: [] },
    ] }],
    attribution: { source: 'Wiktionary', license: 'CC BY-SA', url: '' },
    external_links: [],
  })
  vi.mocked(vocabularyApi.addTranslation).mockResolvedValue({ id: 'T1', text: 'каждый', target_language_code: 'ru', is_primary: true, source_type: 'dictionary' })

  renderCard()
  const add = await screen.findByRole('button', { name: 'Добавить перевод: каждый' })
  fireEvent.click(add)
  await waitFor(() => {
    expect(vocabularyApi.addTranslation).toHaveBeenCalledWith(
      'token', 'I1', expect.objectContaining({ translation_text: 'каждый', source_type: 'dictionary' }),
    )
  })
})

it('does not call AI for a non-new word', async () => {
  vi.mocked(vocabularyApi.lookup).mockResolvedValue({
    item_id: 'I1', status: 'known', confidence: null,
    translations: { primary: null, all: [] }, note: null, tags: [],
  })
  renderCard()
  await screen.findByText('cada')
  const { aiApi } = await import('@/api/ai')
  expect(aiApi.translate).not.toHaveBeenCalled()
})
```

- [ ] **Step 3: Implement suggestions + tags + notes in `WordCard.tsx`**

Add near the top of the component body (after `const m = ...`):

```tsx
  // AI suggestion only for `new` words (needs lesson context; guarded)
  const wantAi = status === 'new'
  const dict = useQuery({
    queryKey: ['dict', lang, target, text ?? ''],
    queryFn: () => dictionaryApi.lookup(lang, target, text as string),
    enabled: text !== null,
  })
  const ai = useQuery({
    queryKey: ['ai-hint', lang, target, text ?? ''],
    queryFn: () => aiApi.translate({
      surface_text: word!.t, context_text: word!.t,
      target_language_code: target, lesson_id: lessonId,
    }),
    enabled: text !== null && wantAi,
    retry: false,
  })
```

Add the required imports at the top:
```tsx
import { useQuery } from '@tanstack/react-query'
import { dictionaryApi } from '@/api/dictionary'
import { aiApi } from '@/api/ai'
```

Build the merged suggestion list (place above the return):

```tsx
  type Suggestion = { text: string; badge: '' | '✦' | '📘'; source: 'user' | 'ai' | 'dictionary' }
  const suggestions: Suggestion[] = [
    ...(data?.translations.all ?? []).map((t) => ({ text: t.text, badge: '' as const, source: 'user' as const })),
    ...(ai.data?.hints ?? []).map((h) => ({ text: h.text, badge: '✦' as const, source: 'ai' as const })),
    ...(dict.data?.entries ?? []).flatMap((e) =>
      e.senses.map((s) => ({ text: s.translation, badge: '📘' as const, source: 'dictionary' as const })),
    ),
  ]

  async function saveSuggestion(sug: Suggestion) {
    const id = itemId ?? (await ensureItem('tracked', 0))
    await m.saveTranslation.mutateAsync({ itemId: id, text: sug.text, source: sug.source })
  }
```

Replace the empty suggestions `<div data-testid="word-card-suggestions" .../>` with:

```tsx
        <div data-testid="word-card-suggestions" className="mt-4">
          {suggestions.length > 0 && <p className="text-sm font-medium">Популярные переводы</p>}
          <ul className="mt-1 space-y-1">
            {suggestions.map((sug, idx) => (
              <li key={`${sug.source}-${idx}`}
                  className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-sm">
                <span className="text-primary">
                  {sug.text}{sug.badge && <span className="ml-2 text-muted-foreground">{sug.badge}</span>}
                </span>
                <button
                  type="button" aria-label={`Добавить перевод: ${sug.text}`}
                  onClick={() => void saveSuggestion(sug)}
                  className="rounded p-1 hover:bg-accent"
                >+</button>
              </li>
            ))}
          </ul>
          {ai.isError && <p className="mt-1 text-sm text-destructive">Не удалось получить AI-перевод</p>}
        </div>
```

Fill the expanded region (tags + notes). Add local state near the other `useState`s:

```tsx
  const [tagDraft, setTagDraft] = useState('')
  const [noteDraft, setNoteDraft] = useState('')
  const noteSavedRef = useRef<string>('')
  useEffect(() => {
    const n = data?.note ?? ''
    setNoteDraft(n)
    noteSavedRef.current = n
  }, [data?.item_id, data?.note])

  async function saveNote() {
    if (!itemId || noteDraft === noteSavedRef.current) return
    noteSavedRef.current = noteDraft
    await m.saveNote.mutateAsync({ itemId, note: noteDraft })
  }
```

Replace the expanded `<div data-testid="word-card-expanded">...</div>` body with:

```tsx
          <div data-testid="word-card-expanded" className="mt-4 space-y-4">
            <div>
              <p className="text-sm font-medium">Теги</p>
              <div className="mt-1 flex flex-wrap gap-2">
                {(data?.tags ?? []).map((tag) => (
                  <button key={tag} type="button"
                    onClick={() => itemId && m.removeTag.mutate({ itemId, tag })}
                    className="rounded-full border border-border px-2 py-0.5 text-xs hover:bg-accent">
                    {tag} ✕
                  </button>
                ))}
                <input
                  className="min-w-24 flex-1 rounded-md border border-border px-2 py-0.5 text-xs"
                  placeholder="Тег+"
                  value={tagDraft}
                  onChange={(e) => setTagDraft(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key === 'Enter' && tagDraft.trim()) {
                      const id = itemId ?? (await ensureItem('tracked', 0))
                      await m.addTag.mutateAsync({ itemId: id, tag: tagDraft.trim() })
                      setTagDraft('')
                    }
                  }}
                />
              </div>
            </div>
            <div>
              <p className="text-sm font-medium">Заметки</p>
              <textarea
                className="mt-1 w-full rounded-md border border-border px-3 py-2 text-sm"
                rows={3}
                value={noteDraft}
                onChange={(e) => setNoteDraft(e.target.value)}
                onBlur={() => void saveNote()}
              />
            </div>
          </div>
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && corepack pnpm exec vitest run src/features/reader/WordCard.test.tsx`
Expected: PASS (all tests).

- [ ] **Step 5: Typecheck**

Run: `cd frontend && corepack pnpm exec tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/reader/WordCard.tsx frontend/src/features/reader/WordCard.test.tsx frontend/src/api/ai.ts
git commit -m "feat(FLQ-5): WordCard suggestions (user/AI/Wiktionary), tags, notes"
```

---

## Task 9: Reader integration + end-to-end verify

**Files:**
- Modify: `frontend/src/features/reader/ReaderPage.tsx`
- Modify: `frontend/src/features/reader/SentenceView.tsx`
- Test: `frontend/src/features/reader/WordCard.test.tsx` (add an integration-style render) + manual verify

**Interfaces:**
- Consumes: `WordCard` (Tasks 7-8).
- Produces: reader renders `<WordCard>` instead of `WordCardPlaceholder`; SentenceView vocab chips show the primary translation instead of `—`.

- [ ] **Step 1: Resolve the target language in ReaderPage**

`WordCard` needs `target` (user's translation language). Reuse the same value ReaderPage already passes to `readerApi.segmentTranslation` (the segment-translation target). Locate that value in `ReaderPage.tsx` (search for `segmentTranslation`/`target`); assign it to a `const targetLang`. If ReaderPage does not currently hold it (translation target is resolved inside `SentenceView`), lift it: add `const targetLang = 'ru'` sourced from the user profile query used elsewhere — verify by searching `translation_language` / `useMe` in `src/features`. Use the located value; do not hardcode if a real source exists.

- [ ] **Step 2: Swap the placeholder for WordCard**

In `ReaderPage.tsx`: replace the import
`import { WordCardPlaceholder } from './WordCardPlaceholder'` → `import { WordCard } from './WordCard'`
and the render block (`ReaderPage.tsx:366-370`):

```tsx
      <WordCard
        word={selectedWord}
        lang={content?.language_code ?? lang}
        target={targetLang}
        lessonId={lessonId}
        onClose={() => setSelectedWord(null)}
      />
```

(`content` is the `useLessonContent` data; if its language field is not in scope, use the route `lang` param already available in ReaderPage.)

- [ ] **Step 3: Close the card on lesson change**

In the lesson-change effect (`ReaderPage.tsx:81-87`) add `setSelectedWord(null)` alongside the other resets.

- [ ] **Step 4: Real translation in SentenceView chips**

`SentenceView` renders tracked words with an em-dash placeholder. The primary translation is not in `statuses` (which only carries `{s,c}`). Minimal, dependency-free change: render the confidence number and keep the word, and drop the `—` (the full translation belongs in the card). Replace the `<span className="text-muted-foreground">—</span>` with nothing, and keep the chip opening the card on click (already wired). This removes the misleading placeholder without adding a per-word lookup.

Update the test id block in `SentenceView.tsx:155-172` accordingly (remove the `—` span).

- [ ] **Step 5: Run the reader test suite**

Run: `cd frontend && corepack pnpm exec vitest run src/features/reader`
Expected: PASS. Fix any `WordCardPlaceholder` references in `ReaderPage.test.tsx` (the test may assert on `word-card-placeholder` test id — update to `word-card`).

- [ ] **Step 6: Delete the dead placeholder**

Run: `cd frontend && rm src/features/reader/WordCardPlaceholder.tsx`
Then re-run `corepack pnpm exec tsc --noEmit` to confirm nothing imports it.

- [ ] **Step 7: Manual end-to-end verify** (invoke the `verify` skill / drive the app)

Ensure API (`uv run flinq serve`) + worker + Vite are running (DB on 5433; run `alembic upgrade head` first). In the browser at `http://localhost:5173`, open a ready lesson, switch to sentence mode:
1. Click a blue (`new`) word → card opens.
2. Type a translation, blur → word turns yellow only after choosing a level; at level 0 it stays blue. Click level `2` → word becomes yellow.
3. Reopen → primary translation is pre-filled; pill `2` highlighted.
4. Click `✓` → highlight disappears (known). Click `🗑` on another word → no highlight (ignored).
Capture a screenshot of the open card for the PR.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/reader/ReaderPage.tsx frontend/src/features/reader/SentenceView.tsx frontend/src/features/reader/WordCard.test.tsx
git rm frontend/src/features/reader/WordCardPlaceholder.tsx
git commit -m "feat(FLQ-5): wire WordCard into reader, drop placeholder"
```

- [ ] **Step 9: Full check + finalize task in backlog**

Run: `cd backend && uv run pytest -q` and `cd frontend && corepack pnpm exec vitest run && corepack pnpm exec tsc --noEmit`
Expected: green. Then mark FLQ-5 acceptance criteria in Backlog and set status In Progress→Done for Increment 1 scope (note deferred items in the task's final summary).

---

## Notes / deviations from the spec (intentional)

- **Wiktionary + AI suggestions are fetched client-side** from the existing `/api/dictionary/lookup` and `/api/ai/translate`, not folded into `/api/vocabulary/lookup`. This mirrors the AI decision in the spec and keeps the vocab lookup focused on user state. (Spec §3.2 wording implied wiktionary inside lookup; this is the cleaner implementation.)
- **Auto-`tracked/0` on annotation is enforced client-side** (the card POSTs `/items {tracked,0}` before the first translation/tag/note on a `new` word); backend `/items` is plain create/ensure. Simpler than server-side auto-create and identical outcome.
- **`/lookup` gained a `target` query param** (needed to pick the primary translation for the user's language). Spec §3.2 listed only `lang`/`text`.
- **SentenceView chips** drop the `—` placeholder rather than render inline translations — the translation lives in the card (avoids an extra per-word fetch this increment).

## Self-review

- **Spec coverage:** §1 scope (token+tags+notes) → Tasks 1-9; §2 confidence model → Task 4 schema validators + Task 7 footer + Task 6 highlight; §2.1 auto-create → Task 7 `ensureItem`; §3 backend tables/endpoints → Tasks 1-4; §3.3 reader highlight → Task 6; §4 frontend card (collapsed/expanded, layouts, debounced save, hotkeys) → Tasks 5,7,8,9; §5 error/loading (AI disabled/error) → Task 8 (`ai.isError`, guarded `wantAi`); §6 tests → each task. Deferred (§1) phrases/external-dicts/TTS — not scheduled, as intended.
- **Placeholder scan:** the `_map_service_errors` stub in Task 4 Step 4 is explicitly flagged for deletion; no other stubs.
- **Type consistency:** `WriteStatus` (`tracked|known|ignored`) vs `CardStatus` (adds `new`) used consistently; `setStatus` mutation accepts `itemId: string|null` and branches create/patch; `ensureItem` returns the new id used by translation/tag saves.
