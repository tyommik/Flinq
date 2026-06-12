# Lesson Processing Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn imported lesson text into persisted lesson *facts* — segments and token occurrences — produced by an asynchronous worker import job, so token-level features can be built on top.

**Architecture:** `POST /api/lessons` creates a `processing` lesson + a `lesson_sources` row + a `lesson_import_jobs` row, enqueues a taskiq job, and returns `202 {id, status}`. The job (also callable directly as a plain async function) NFC-normalizes the text, splits it into paragraphs then sentences, tokenizes each sentence, bulk-inserts `lesson_segments` and `lesson_token_occurrences`, sets counts, and flips the lesson to `ready` — or `failed` with an `error_message`. Retry is idempotent: facts are deleted and recreated, allowed only while the lesson is not yet `ready`. The lesson row is locked `FOR UPDATE` and the worker runs a specific `job_id` (not "the latest job"), so duplicate/concurrent delivery serializes instead of double-processing; if the queue is unavailable the request marks the lesson `failed` and returns 503 rather than stranding it in `processing`. Tokenization/segmentation are pure functions behind a `Segmenter` protocol.

**Tech Stack:** Python 3.13, async SQLAlchemy 2 (`Mapped[...]`), Alembic, Pydantic v2, taskiq (existing Redis/InMemory broker), Postgres (asyncpg), pytest + testcontainers, loguru. Languages: `en`, `ru`, `pt`. Branch: `feat/flq-1-lesson-pipeline`.

**Spec:** `docs/superpowers/specs/2026-05-30-lesson-processing-pipeline-design.md`

---

## Orientation (read before starting)

Existing code you will extend (already on disk):

- `backend/src/flinq/modules/lesson_library/models.py` — only `Lesson` today (`status` defaults to `"ready"`).
- `backend/src/flinq/modules/lesson_library/repo.py` — `LessonRepo.list_for_user`, `LessonRepo.create`.
- `backend/src/flinq/modules/lesson_library/service.py` — `create_lesson_from_text` (synchronous, sets `ready`).
- `backend/src/flinq/modules/lesson_library/schemas.py` — `CreateLessonRequest`, `LessonSummary`, `LessonListResponse`.
- `backend/src/flinq/api/lessons.py` — `GET /api/lessons`, `POST /api/lessons` (returns `201`).
- `backend/src/flinq/worker/tasks.py` — taskiq tasks (`ping`, `cleanup_expired_sessions`); broker in `worker/broker.py` (InMemory in `env=test`).
- `backend/migrations/versions/0002_lessons_minimal.py` — current Alembic head (`revision = "0002_lessons_minimal"`).
- `backend/migrations/env.py` — already imports `lesson_library.models` for autogenerate.
- `backend/tests/conftest.py` — session-scoped Postgres + Redis testcontainers; `_init_schema` builds the schema with `Base.metadata.create_all` (NOT Alembic); `db_session` and `client` fixtures; auth tests register via `/auth/register` + `/me/onboarding` and pass `X-CSRF-Token`.

Test harness facts that shape this plan:

- The test DB schema comes from `create_all`, so new ORM models appear automatically once imported. Task 1 also adds an explicit import in `conftest._init_schema` for robustness.
- DB/API tests run against real Postgres; pure tokenizer tests need no DB.
- `env=test` uses `InMemoryBroker`, which **executes a task inline when `.kiq()` is called**. To keep the API test deterministic, the POST handler enqueues through a thin `enqueue_lesson_import()` helper that tests monkeypatch; the worker job itself is tested by calling the service function directly (per the spec's testing strategy).

Conventions to copy:
- Run all backend commands from `backend/` (e.g. `cd backend && uv run pytest ...`).
- `from __future__ import annotations` at the top of every module.
- ORM uses `Mapped[...] = mapped_column(...)`, `UUID(as_uuid=True)`, `server_default=text("now()")`.
- Endpoints read `request.state.user_id` (set by `SessionMiddleware`) and raise `HTTPException(status.HTTP_401_UNAUTHORIZED)` when missing.

---

## Task 1: Data model — ORM tables for the pipeline

**Files:**
- Modify: `backend/src/flinq/modules/lesson_library/models.py`
- Modify: `backend/tests/conftest.py` (add models import in `_init_schema`)
- Test: `backend/tests/modules/lesson_library/test_models_schema.py` (create)
- Create (empty package markers): `backend/tests/modules/lesson_library/__init__.py`

- [ ] **Step 1: Create the test package marker**

Create `backend/tests/modules/lesson_library/__init__.py` with a single empty line (file may be empty). This makes the directory a package consistent with the existing `backend/tests/modules/identity/`.

- [ ] **Step 2: Write the failing schema test**

Create `backend/tests/modules/lesson_library/test_models_schema.py`:

```python
"""Schema-level checks for the lesson pipeline tables (AC#1, AC#5)."""

from __future__ import annotations

from sqlalchemy import inspect

from flinq.core.db import get_engine


async def test_pipeline_tables_exist() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert {
        "lesson_sources",
        "lesson_segments",
        "lesson_token_occurrences",
        "lesson_import_jobs",
    } <= tables


async def test_lessons_has_new_columns() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("lessons")}
        )
    assert "segment_count" in cols
    assert "current_source_version" in cols


async def test_occurrence_unique_constraint() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        uniques = await conn.run_sync(
            lambda c: {
                uc["name"] for uc in inspect(c).get_unique_constraints("lesson_token_occurrences")
            }
        )
    assert "uq_occurrence_lesson_ordinal" in uniques
```

Note: `get_engine` is added in Step 4 if it does not exist; check `backend/src/flinq/core/db.py` first — it exposes `init_engine`/`dispose_engine`. If there is no `get_engine`, use the module-level `_engine` accessor pattern below in Step 4.

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_models_schema.py -v`
Expected: FAIL — tables/columns/constraint do not exist yet (or `ImportError` for `get_engine`).

- [ ] **Step 4: Add a `get_engine` accessor if missing**

Open `backend/src/flinq/core/db.py`. If there is no public `get_engine()`, add one next to `init_engine`:

```python
def get_engine() -> AsyncEngine:
    """Return the initialized async engine (raises if not initialized)."""
    if _engine is None:
        raise RuntimeError("Engine not initialized; call init_engine() first.")
    return _engine
```

Ensure `AsyncEngine` is imported in that file (`from sqlalchemy.ext.asyncio import AsyncEngine`). If `get_engine` already exists, skip this step.

- [ ] **Step 5: Implement the ORM models**

Replace the full contents of `backend/src/flinq/modules/lesson_library/models.py` with:

```python
"""Lesson library models: lessons plus the processing-pipeline facts.

Lesson *facts* (sources, segments, token occurrences) are stored separately
from per-user knowledge. Occurrences deliberately have NO foreign key to
token_items; the link is computed later via
(user_id, lesson.language_code, normalized_text). See domain model §2.4, §6.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
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

LessonStatus = Literal["draft", "processing", "ready", "failed", "archived"]
LessonVisibility = Literal["private", "shared"]
SegmentType = Literal["sentence", "paragraph"]
SourceType = Literal["manual", "file", "url", "ocr"]
JobStatus = Literal["pending", "running", "done", "failed"]


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    language_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    visibility: Mapped[LessonVisibility] = mapped_column(
        String(16), nullable=False, default="private"
    )
    status: Mapped[LessonStatus] = mapped_column(String(16), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=func.now(),
    )


class LessonSource(Base):
    __tablename__ = "lesson_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[SourceType] = mapped_column(String(16), nullable=False, default="manual")
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    license: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LessonSegment(Base):
    __tablename__ = "lesson_segments"
    __table_args__ = (
        UniqueConstraint("lesson_id", "ordinal", name="uq_segment_lesson_ordinal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_type: Mapped[SegmentType] = mapped_column(String(16), nullable=False, default="sentence")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_char_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char_offset: Mapped[int] = mapped_column(Integer, nullable=False)


class LessonTokenOccurrence(Base):
    __tablename__ = "lesson_token_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "lesson_id", "ordinal_in_lesson", name="uq_occurrence_lesson_ordinal"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lesson_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal_in_lesson: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal_in_segment: Mapped[int] = mapped_column(Integer, nullable=False)
    surface_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    start_char_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    is_word_like: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class LessonImportJob(Base):
    __tablename__ = "lesson_import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, default="import_text")
    status: Mapped[JobStatus] = mapped_column(String(16), nullable=False, default="pending")
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
```

- [ ] **Step 6: Ensure the test schema includes the new models**

In `backend/tests/conftest.py`, inside `_init_schema`, add an explicit import next to the identity import (around line 57) so `create_all` always registers the pipeline tables:

```python
    from flinq.modules.identity import models as _identity_models  # noqa: F401
    from flinq.modules.lesson_library import models as _lesson_models  # noqa: F401
```

- [ ] **Step 7: Run the schema test to verify it passes**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_models_schema.py -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add backend/src/flinq/modules/lesson_library/models.py backend/src/flinq/core/db.py backend/tests/conftest.py backend/tests/modules/lesson_library/
git commit -m "feat(lessons): add pipeline ORM models (sources, segments, occurrences, jobs)"
```

---

## Task 2: Alembic migration for the pipeline tables (AC#1)

**Files:**
- Create: `backend/migrations/versions/0003_lesson_pipeline.py`
- Test: `backend/tests/modules/lesson_library/test_migration_chain.py` (create)

Context: The test DB is built with `create_all`, not Alembic, so this migration is what makes a *production* database match the ORM. We verify it two ways: (a) a unit test asserting the revision chains from the current head and exposes `upgrade`/`downgrade`; (b) the Task 1 schema test already proves the ORM tables are correct. A manual `alembic upgrade head` against a clean DB is included as a final check in Task 8.

- [ ] **Step 1: Write the failing migration-chain test**

Create `backend/tests/modules/lesson_library/test_migration_chain.py`:

```python
"""The pipeline migration must chain from the current head (AC#1)."""

from __future__ import annotations

import importlib


def test_migration_chains_from_lessons_minimal() -> None:
    mod = importlib.import_module("migrations.versions.0003_lesson_pipeline")
    assert mod.revision == "0003_lesson_pipeline"
    assert mod.down_revision == "0002_lessons_minimal"
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)
```

Note: `migrations` is importable because `backend/` is on the path when running pytest from `backend/`. If the dotted import fails due to the leading digit, fall back to `importlib.import_module` of the path via `importlib.util` — but the digit-prefixed module name works with `import_module` since it takes a string.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_migration_chain.py -v`
Expected: FAIL — module `0003_lesson_pipeline` does not exist.

- [ ] **Step 3: Write the migration**

Create `backend/migrations/versions/0003_lesson_pipeline.py`:

```python
"""lesson processing pipeline

Revision ID: 0003_lesson_pipeline
Revises: 0002_lessons_minimal
Create Date: 2026-05-31 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_lesson_pipeline"
down_revision: str | Sequence[str] | None = "0002_lessons_minimal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lessons",
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "lessons",
        sa.Column(
            "current_source_version", sa.Integer(), nullable=False, server_default="1"
        ),
    )

    op.create_table(
        "lesson_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("license", sa.String(length=100), nullable=True),
        sa.Column("source_label", sa.String(length=200), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lesson_sources_lesson_id"), "lesson_sources", ["lesson_id"], unique=False
    )

    op.create_table(
        "lesson_segments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("segment_type", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_char_offset", sa.Integer(), nullable=False),
        sa.Column("end_char_offset", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lesson_id", "ordinal", name="uq_segment_lesson_ordinal"),
    )
    op.create_index(
        op.f("ix_lesson_segments_lesson_id"), "lesson_segments", ["lesson_id"], unique=False
    )

    op.create_table(
        "lesson_token_occurrences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("segment_id", sa.UUID(), nullable=False),
        sa.Column("ordinal_in_lesson", sa.Integer(), nullable=False),
        sa.Column("ordinal_in_segment", sa.Integer(), nullable=False),
        sa.Column("surface_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("start_char_offset", sa.Integer(), nullable=False),
        sa.Column("end_char_offset", sa.Integer(), nullable=False),
        sa.Column("is_word_like", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["lesson_segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lesson_id", "ordinal_in_lesson", name="uq_occurrence_lesson_ordinal"
        ),
    )
    op.create_index(
        op.f("ix_lesson_token_occurrences_lesson_id"),
        "lesson_token_occurrences",
        ["lesson_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lesson_token_occurrences_segment_id"),
        "lesson_token_occurrences",
        ["segment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lesson_token_occurrences_normalized_text"),
        "lesson_token_occurrences",
        ["normalized_text"],
        unique=False,
    )

    op.create_table(
        "lesson_import_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.UUID(), nullable=False),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lesson_import_jobs_lesson_id"),
        "lesson_import_jobs",
        ["lesson_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_lesson_import_jobs_lesson_id"), table_name="lesson_import_jobs")
    op.drop_table("lesson_import_jobs")
    op.drop_index(
        op.f("ix_lesson_token_occurrences_normalized_text"),
        table_name="lesson_token_occurrences",
    )
    op.drop_index(
        op.f("ix_lesson_token_occurrences_segment_id"),
        table_name="lesson_token_occurrences",
    )
    op.drop_index(
        op.f("ix_lesson_token_occurrences_lesson_id"),
        table_name="lesson_token_occurrences",
    )
    op.drop_table("lesson_token_occurrences")
    op.drop_index(op.f("ix_lesson_segments_lesson_id"), table_name="lesson_segments")
    op.drop_table("lesson_segments")
    op.drop_index(op.f("ix_lesson_sources_lesson_id"), table_name="lesson_sources")
    op.drop_table("lesson_sources")
    op.drop_column("lessons", "current_source_version")
    op.drop_column("lessons", "segment_count")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_migration_chain.py -v`
Expected: PASS.

- [ ] **Step 5: Confirm the migration history is linear**

Run: `cd backend && uv run alembic history`
Expected: shows `0001_identity -> 0002_lessons_minimal -> 0003_lesson_pipeline (head)`. No "multiple heads" warning.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/0003_lesson_pipeline.py backend/tests/modules/lesson_library/test_migration_chain.py
git commit -m "feat(lessons): add alembic migration for pipeline tables"
```

---

## Task 3: Tokenizer — `normalize_token`, `is_word_like`, `tokenize` (AC#2)

**Files:**
- Create: `backend/src/flinq/modules/lesson_library/tokenization.py`
- Test: `backend/tests/modules/lesson_library/test_tokenization.py` (create)

- [ ] **Step 1: Write the failing tokenizer tests**

Create `backend/tests/modules/lesson_library/test_tokenization.py`:

```python
"""Unit tests for tokenization primitives (AC#2). No DB."""

from __future__ import annotations

from flinq.modules.lesson_library.tokenization import (
    Token,
    is_word_like,
    normalize_token,
    tokenize,
)


def test_normalize_lowercases_and_trims_outer_punctuation() -> None:
    assert normalize_token("Mundo.") == "mundo"
    assert normalize_token("«Olá»") == "olá"
    assert normalize_token("HELLO!") == "hello"


def test_normalize_preserves_diacritics() -> None:
    assert normalize_token("Não.") == "não"
    assert normalize_token("Café,") == "café"
    assert normalize_token("Что-то") == "что-то"


def test_normalize_preserves_internal_hyphen_and_apostrophe() -> None:
    assert normalize_token("co-op,") == "co-op"
    assert normalize_token("L'eau") == "l'eau"
    assert normalize_token("don't") == "don't"


def test_normalize_punctuation_only_is_empty() -> None:
    assert normalize_token("...") == ""
    assert normalize_token(",") == ""


def test_is_word_like() -> None:
    assert is_word_like("mundo") is True
    assert is_word_like("co-op") is True
    assert is_word_like("3.14") is True
    assert is_word_like(".") is False
    assert is_word_like("—") is False


def test_tokenize_splits_words_and_punctuation_with_offsets() -> None:
    tokens = tokenize("Olá mundo.")
    assert [t.surface_text for t in tokens] == ["Olá", "mundo", "."]
    assert [t.normalized_text for t in tokens] == ["olá", "mundo", ""]
    assert [t.is_word_like for t in tokens] == [True, True, False]
    # offsets index back into the source string
    first = tokens[0]
    assert "Olá mundo."[first.start_char_offset : first.end_char_offset] == "Olá"
    period = tokens[-1]
    assert "Olá mundo."[period.start_char_offset : period.end_char_offset] == "."


def test_tokenize_keeps_internal_marks_as_one_token() -> None:
    tokens = tokenize("co-op l'eau")
    assert [t.surface_text for t in tokens] == ["co-op", "l'eau"]
    assert all(isinstance(t, Token) for t in tokens)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_tokenization.py -v`
Expected: FAIL — module `tokenization` not found.

- [ ] **Step 3: Implement the tokenizer primitives**

Create `backend/src/flinq/modules/lesson_library/tokenization.py`:

```python
"""Segmentation and tokenization for lesson text (ADR-0001).

Pure functions only — no DB, no I/O. `normalize_token` is the canonical
join key shared between lesson occurrences and the future vocabulary layer.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# A word: a run of word chars that may contain internal hyphens/apostrophes,
# OR a single word char, OR a run of punctuation (non-word, non-space).
_TOKEN_RE = re.compile(r"\w[\w'’\-]*\w|\w|[^\w\s]+", re.UNICODE)
_OUTER_PUNCT_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)
_WORD_CHAR_RE = re.compile(r"\w", re.UNICODE)


@dataclass(frozen=True)
class Token:
    surface_text: str
    normalized_text: str
    start_char_offset: int
    end_char_offset: int
    is_word_like: bool


def normalize_token(surface: str) -> str:
    """NFC, lowercase, strip outer punctuation; keep diacritics + internal -/'."""
    s = unicodedata.normalize("NFC", surface).lower()
    s = _OUTER_PUNCT_RE.sub("", s)
    return s


def is_word_like(surface: str) -> bool:
    """True if the token contains at least one word character."""
    return bool(_WORD_CHAR_RE.search(unicodedata.normalize("NFC", surface)))


def tokenize(text: str, *, base_offset: int = 0) -> list[Token]:
    """Split text into word and punctuation tokens with absolute char offsets.

    `base_offset` is added to every offset so callers can tokenize a slice of a
    larger document and keep offsets relative to the whole document.
    """
    tokens: list[Token] = []
    for m in _TOKEN_RE.finditer(text):
        surface = m.group(0)
        tokens.append(
            Token(
                surface_text=surface,
                normalized_text=normalize_token(surface),
                start_char_offset=base_offset + m.start(),
                end_char_offset=base_offset + m.end(),
                is_word_like=is_word_like(surface),
            )
        )
    return tokens
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_tokenization.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/flinq/modules/lesson_library/tokenization.py backend/tests/modules/lesson_library/test_tokenization.py
git commit -m "feat(lessons): add token normalization and tokenizer (ADR-0001)"
```

---

## Task 4: Segmenter — `Segmenter` protocol + `RegexSegmenter` (AC#2)

**Files:**
- Modify: `backend/src/flinq/modules/lesson_library/tokenization.py`
- Test: `backend/tests/modules/lesson_library/test_segmenter.py` (create)

- [ ] **Step 1: Write the failing segmenter tests**

Create `backend/tests/modules/lesson_library/test_segmenter.py`:

```python
"""Unit tests for sentence/paragraph segmentation (AC#2). No DB."""

from __future__ import annotations

from flinq.modules.lesson_library.tokenization import RegexSegmenter, Span


def _texts(spans: list[Span]) -> list[str]:
    return [s.text for s in spans]


def test_paragraphs_split_on_blank_lines() -> None:
    seg = RegexSegmenter("en")
    spans = seg.split_paragraphs("First para.\n\nSecond para.")
    assert _texts(spans) == ["First para.", "Second para."]


def test_paragraph_offsets_index_back_into_source() -> None:
    seg = RegexSegmenter("en")
    src = "First para.\n\nSecond para."
    spans = seg.split_paragraphs(src)
    for s in spans:
        assert src[s.start : s.end] == s.text


def test_english_abbreviation_does_not_split() -> None:
    seg = RegexSegmenter("en")
    spans = seg.split_sentences("Mr. Smith left. He waved.")
    assert _texts(spans) == ["Mr. Smith left.", "He waved."]


def test_english_decimal_does_not_split() -> None:
    seg = RegexSegmenter("en")
    spans = seg.split_sentences("Pi is 3.14 today. Yes.")
    assert _texts(spans) == ["Pi is 3.14 today.", "Yes."]


def test_russian_abbreviation_does_not_split() -> None:
    seg = RegexSegmenter("ru")
    spans = seg.split_sentences("Купи хлеб, молоко и т.д. Потом приходи.")
    assert _texts(spans) == ["Купи хлеб, молоко и т.д.", "Потом приходи."]


def test_portuguese_abbreviation_does_not_split() -> None:
    seg = RegexSegmenter("pt")
    spans = seg.split_sentences("A Dr.ª Ana chegou. Ela sorriu.")
    assert _texts(spans) == ["A Dr.ª Ana chegou.", "Ela sorriu."]


def test_initials_do_not_split() -> None:
    seg = RegexSegmenter("ru")
    spans = seg.split_sentences("Пришёл А. С. Пушкин.")
    assert len(spans) == 1


def test_sentence_offsets_index_back_into_source() -> None:
    seg = RegexSegmenter("en")
    src = "One. Two."
    spans = seg.split_sentences(src)
    for s in spans:
        assert src[s.start : s.end] == s.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_segmenter.py -v`
Expected: FAIL — `Span` / `RegexSegmenter` not defined.

- [ ] **Step 3: Add the `Span`, `Segmenter` protocol, and `RegexSegmenter`**

Append to `backend/src/flinq/modules/lesson_library/tokenization.py` (after the existing code; also add `Protocol` to imports):

At the top, change the imports block to include `typing.Protocol`:

```python
from typing import Protocol
```

Then append:

```python
@dataclass(frozen=True)
class Span:
    text: str
    start: int
    end: int


class Segmenter(Protocol):
    """Splits text into paragraphs and sentences with absolute offsets."""

    def split_paragraphs(self, text: str) -> list[Span]: ...

    def split_sentences(self, paragraph: str, *, base_offset: int = 0) -> list[Span]: ...


# Per-language abbreviations (lowercased, without the trailing period).
_ABBREVIATIONS: dict[str, frozenset[str]] = {
    "en": frozenset(
        {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc",
         "inc", "ltd", "co", "no", "fig", "e.g", "i.e", "approx"}
    ),
    "ru": frozenset(
        {"т", "д", "п", "г", "гг", "стр", "рис", "см", "им", "др", "пр",
         "тыс", "руб", "коп", "ул", "обл"}
    ),
    "pt": frozenset(
        {"sr", "sra", "dr", "dra", "prof", "profa", "ex", "av", "núm",
         "pág", "etc", "ltda", "esq"}
    ),
}

_PARA_SPLIT_RE = re.compile(r"\n[ \t]*\n+")
_SENT_PUNCT_RE = re.compile(r"[.!?…]+")
_LAST_WORD_RE = re.compile(r"(\w+)$", re.UNICODE)
_SENTENCE_START_CHARS = "\"'«“(-—"


def _trim_to_span(chunk: str, start: int) -> Span:
    """Strip surrounding whitespace from chunk and return a Span with offsets."""
    stripped = chunk.strip()
    lead = len(chunk) - len(chunk.lstrip())
    real_start = start + lead
    return Span(text=stripped, start=real_start, end=real_start + len(stripped))


class RegexSegmenter:
    """Rule-based segmenter for en/ru/pt. Swap-in for the Segmenter protocol."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self._abbrevs = _ABBREVIATIONS.get(lang, frozenset())

    def split_paragraphs(self, text: str) -> list[Span]:
        spans: list[Span] = []
        pos = 0
        for m in _PARA_SPLIT_RE.finditer(text):
            chunk = text[pos : m.start()]
            if chunk.strip():
                spans.append(_trim_to_span(chunk, pos))
            pos = m.end()
        tail = text[pos:]
        if tail.strip():
            spans.append(_trim_to_span(tail, pos))
        return spans

    def split_sentences(self, paragraph: str, *, base_offset: int = 0) -> list[Span]:
        spans: list[Span] = []
        n = len(paragraph)
        start = 0
        for m in _SENT_PUNCT_RE.finditer(paragraph):
            end = m.end()
            after = paragraph[end : end + 1]
            # Boundary candidate only when followed by whitespace or end-of-text.
            if after and not after.isspace():
                continue
            # Skip abbreviations and single-letter initials right before the dot.
            prefix = paragraph[start : m.start()]
            lw = _LAST_WORD_RE.search(prefix)
            if lw is not None:
                word = lw.group(1)
                if word.lower() in self._abbrevs or len(word) == 1:
                    continue
            # Require the next non-space char to look like a sentence start.
            j = end
            while j < n and paragraph[j].isspace():
                j += 1
            if j < n:
                nxt = paragraph[j]
                if not (nxt.isupper() or nxt.isdigit() or nxt in _SENTENCE_START_CHARS):
                    continue
            spans.append(_trim_to_span(paragraph[start:end], base_offset + start))
            start = end
        tail = paragraph[start:]
        if tail.strip():
            spans.append(_trim_to_span(tail, base_offset + start))
        return spans
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_segmenter.py -v`
Expected: PASS (8 tests).

If `test_initials_do_not_split` fails because "С." is followed by "Пушкин" (uppercase) and "С" is a single letter — the single-letter guard handles "А." and "С." individually, so both boundaries are skipped. Confirm the guard order matches the code above (single-letter check happens before the uppercase-next check).

- [ ] **Step 5: Commit**

```bash
git add backend/src/flinq/modules/lesson_library/tokenization.py backend/tests/modules/lesson_library/test_segmenter.py
git commit -m "feat(lessons): add RegexSegmenter behind Segmenter protocol (en/ru/pt)"
```

---

## Task 5: Import service — build facts, idempotent, callable directly (AC#5, AC#6)

**Files:**
- Modify: `backend/src/flinq/modules/lesson_library/repo.py`
- Modify: `backend/src/flinq/modules/lesson_library/service.py`
- Test: `backend/tests/modules/lesson_library/test_import_service.py` (create)

- [ ] **Step 1: Write the failing service tests**

Create `backend/tests/modules/lesson_library/test_import_service.py`:

```python
"""Import service: round-trip, ordering, idempotency, immutability (AC#5, AC#6)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.identity.repo import UserRepo
from flinq.modules.lesson_library import service
from flinq.modules.lesson_library.models import (
    Lesson,
    LessonSegment,
    LessonTokenOccurrence,
)
from flinq.modules.lesson_library.repo import LessonRepo

TEXT = "Olá mundo. Como vai você?\n\nTudo bem aqui."


async def _make_processing_lesson(session: AsyncSession) -> uuid.UUID:
    user = await UserRepo(session).create(
        email=f"imp-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name="T",
        role="learner",
    )
    await session.flush()
    lesson = await LessonRepo(session).create_processing_lesson(
        owner_user_id=user.id,
        title="T",
        language_code="pt",
        raw_text=TEXT,
        visibility="private",
    )
    await session.flush()
    return lesson.id


async def _count(session: AsyncSession, model, lesson_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(model).where(model.lesson_id == lesson_id)
    return (await session.execute(stmt)).scalar_one()


async def test_round_trip_marks_ready_and_creates_facts(db_session: AsyncSession) -> None:
    lesson_id = await _make_processing_lesson(db_session)

    await service.process_lesson_import(db_session, lesson_id)

    lesson = await db_session.get(Lesson, lesson_id)
    assert lesson is not None
    assert lesson.status == "ready"
    assert lesson.segment_count == await _count(db_session, LessonSegment, lesson_id)
    assert lesson.word_count > 0
    assert await _count(db_session, LessonTokenOccurrence, lesson_id) > 0


async def test_occurrence_ordinals_are_unique_and_ordered(db_session: AsyncSession) -> None:
    lesson_id = await _make_processing_lesson(db_session)
    await service.process_lesson_import(db_session, lesson_id)

    stmt = (
        select(LessonTokenOccurrence.ordinal_in_lesson)
        .where(LessonTokenOccurrence.lesson_id == lesson_id)
        .order_by(LessonTokenOccurrence.ordinal_in_lesson)
    )
    ordinals = [row[0] for row in (await db_session.execute(stmt)).all()]
    assert ordinals == list(range(len(ordinals)))


async def test_retry_is_idempotent(db_session: AsyncSession) -> None:
    lesson_id = await _make_processing_lesson(db_session)

    await service.process_lesson_import(db_session, lesson_id)
    occ_first = await _count(db_session, LessonTokenOccurrence, lesson_id)
    seg_first = await _count(db_session, LessonSegment, lesson_id)

    # Force back to a re-runnable state and run again.
    lesson = await db_session.get(Lesson, lesson_id)
    assert lesson is not None
    lesson.status = "failed"
    await db_session.flush()
    await service.process_lesson_import(db_session, lesson_id)

    assert await _count(db_session, LessonTokenOccurrence, lesson_id) == occ_first
    assert await _count(db_session, LessonSegment, lesson_id) == seg_first


async def test_ready_lesson_is_not_reprocessed(db_session: AsyncSession) -> None:
    lesson_id = await _make_processing_lesson(db_session)
    await service.process_lesson_import(db_session, lesson_id)

    with pytest.raises(service.LessonNotProcessable):
        await service.process_lesson_import(db_session, lesson_id)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_import_service.py -v`
Expected: FAIL — `create_processing_lesson`, `process_lesson_import`, `LessonNotProcessable` do not exist.

- [ ] **Step 3: Extend the repo**

Replace the full contents of `backend/src/flinq/modules/lesson_library/repo.py` with:

```python
"""Lesson repository: list, create, and pipeline-fact persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import (
    Lesson,
    LessonImportJob,
    LessonSegment,
    LessonSource,
    LessonTokenOccurrence,
)


class LessonRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        lang: str,
        q: str | None = None,
        visibility: str = "all",
        tab: str = "lessons",
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[Lesson], int]:
        stmt = select(Lesson).where(
            Lesson.language_code == lang,
            Lesson.status != "archived",
            or_(
                Lesson.owner_user_id == user_id,
                Lesson.visibility == "shared",
            ),
        )
        if q:
            stmt = stmt.where(Lesson.title.ilike(f"%{q}%"))
        if visibility == "mine":
            stmt = stmt.where(Lesson.owner_user_id == user_id)
        elif visibility == "shared":
            stmt = stmt.where(Lesson.visibility == "shared")

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            stmt.order_by(Lesson.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create_processing_lesson(
        self,
        *,
        owner_user_id: uuid.UUID,
        title: str,
        language_code: str,
        raw_text: str,
        visibility: str,
    ) -> Lesson:
        lesson = Lesson(
            owner_user_id=owner_user_id,
            title=title,
            language_code=language_code,
            raw_text=raw_text,
            visibility=visibility,
            word_count=0,
            segment_count=0,
            current_source_version=1,
            status="processing",
        )
        self.session.add(lesson)
        await self.session.flush()
        return lesson

    async def add_source(
        self,
        *,
        lesson_id: uuid.UUID,
        content_hash: str,
        source_type: str = "manual",
        version_number: int = 1,
    ) -> LessonSource:
        source = LessonSource(
            lesson_id=lesson_id,
            content_hash=content_hash,
            source_type=source_type,
            version_number=version_number,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def add_import_job(
        self,
        *,
        lesson_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        job_type: str = "import_text",
    ) -> LessonImportJob:
        job = LessonImportJob(
            lesson_id=lesson_id,
            requested_by_user_id=requested_by_user_id,
            job_type=job_type,
            status="pending",
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_lesson(self, lesson_id: uuid.UUID) -> Lesson | None:
        return await self.session.get(Lesson, lesson_id)

    async def lock_lesson(self, lesson_id: uuid.UUID) -> Lesson | None:
        """Fetch a lesson with a row-level lock (FOR UPDATE).

        Serializes concurrent/duplicate import runs for the same lesson so the
        delete-and-recreate of facts cannot interleave (review finding #2).
        """
        stmt = select(Lesson).where(Lesson.id == lesson_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_job(self, job_id: uuid.UUID) -> LessonImportJob | None:
        return await self.session.get(LessonImportJob, job_id)

    async def lock_job(self, job_id: uuid.UUID) -> LessonImportJob | None:
        """Fetch an import job with a row-level lock (FOR UPDATE).

        Lets the worker enforce a single pending/running transition even under
        duplicate task delivery (review finding #2).
        """
        stmt = select(LessonImportJob).where(LessonImportJob.id == job_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def delete_facts(self, lesson_id: uuid.UUID) -> None:
        """Remove all segments + occurrences for a lesson (occurrences first)."""
        await self.session.execute(
            delete(LessonTokenOccurrence).where(LessonTokenOccurrence.lesson_id == lesson_id)
        )
        await self.session.execute(
            delete(LessonSegment).where(LessonSegment.lesson_id == lesson_id)
        )
        await self.session.flush()
```

- [ ] **Step 4: Implement the import service**

Replace the full contents of `backend/src/flinq/modules/lesson_library/service.py` with:

```python
"""Lesson library service: lesson creation and the import pipeline."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import (
    Lesson,
    LessonSegment,
    LessonTokenOccurrence,
)
from flinq.modules.lesson_library.repo import LessonRepo
from flinq.modules.lesson_library.tokenization import RegexSegmenter, tokenize

# Lesson statuses from which (re)processing is allowed. A `ready` lesson is
# immutable (domain model §14.1), so it is never reprocessed.
_PROCESSABLE = {"processing", "failed"}


class LessonNotFound(Exception):
    """Raised when a lesson id does not exist."""


class LessonNotProcessable(Exception):
    """Raised when import is attempted on a lesson that is not re-runnable."""


def content_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


async def create_lesson_for_import(
    *,
    owner_user_id: uuid.UUID,
    title: str,
    language_code: str,
    raw_text: str,
    visibility: str,
    repo: LessonRepo,
) -> tuple[Lesson, uuid.UUID]:
    """Create a processing lesson + v1 source + pending job. Returns (lesson, job_id)."""
    lesson = await repo.create_processing_lesson(
        owner_user_id=owner_user_id,
        title=title,
        language_code=language_code,
        raw_text=raw_text,
        visibility=visibility,
    )
    await repo.add_source(lesson_id=lesson.id, content_hash=content_hash(raw_text))
    job = await repo.add_import_job(lesson_id=lesson.id, requested_by_user_id=owner_user_id)
    return lesson, job.id


async def mark_import_failed(
    session: AsyncSession,
    *,
    lesson_id: uuid.UUID,
    job_id: uuid.UUID,
    error: str,
) -> None:
    """Flip a lesson + its import job to failed (used when enqueue cannot happen).

    Never downgrades a lesson that already reached ready. Caller commits.
    """
    repo = LessonRepo(session)
    lesson = await repo.get_lesson(lesson_id)
    if lesson is not None and lesson.status != "ready":
        lesson.status = "failed"
    job = await repo.get_job(job_id)
    if job is not None:
        job.status = "failed"
        job.error_message = error
        job.finished_at = datetime.now(timezone.utc)
    await session.flush()


async def process_lesson_import(session: AsyncSession, lesson_id: uuid.UUID) -> None:
    """Segment + tokenize a lesson's text into facts, then mark it ready.

    Idempotent and concurrency-safe: the lesson row is locked FOR UPDATE and its
    status re-checked under the lock, so duplicate/concurrent runs serialize and
    a ready lesson is never mutated. Existing facts are deleted before re-insert.
    Allowed only while the lesson status is in {processing, failed}.
    """
    repo = LessonRepo(session)
    lesson = await repo.lock_lesson(lesson_id)  # FOR UPDATE: serialize concurrent runs
    if lesson is None:
        raise LessonNotFound(str(lesson_id))
    if lesson.status not in _PROCESSABLE:  # re-checked while holding the row lock
        raise LessonNotProcessable(f"lesson {lesson_id} is {lesson.status}")

    await repo.delete_facts(lesson_id)

    segmenter = RegexSegmenter(lesson.language_code)
    word_count = 0
    segment_ordinal = 0
    occ_ordinal = 0

    for paragraph in segmenter.split_paragraphs(lesson.raw_text):
        for sentence in segmenter.split_sentences(paragraph.text, base_offset=paragraph.start):
            segment = LessonSegment(
                lesson_id=lesson_id,
                ordinal=segment_ordinal,
                segment_type="sentence",
                text=sentence.text,
                start_char_offset=sentence.start,
                end_char_offset=sentence.end,
            )
            session.add(segment)
            await session.flush()  # assign segment.id for the occurrence FK

            for seg_idx, tok in enumerate(
                tokenize(sentence.text, base_offset=sentence.start)
            ):
                session.add(
                    LessonTokenOccurrence(
                        lesson_id=lesson_id,
                        segment_id=segment.id,
                        ordinal_in_lesson=occ_ordinal,
                        ordinal_in_segment=seg_idx,
                        surface_text=tok.surface_text,
                        normalized_text=tok.normalized_text,
                        start_char_offset=tok.start_char_offset,
                        end_char_offset=tok.end_char_offset,
                        is_word_like=tok.is_word_like,
                    )
                )
                occ_ordinal += 1
                if tok.is_word_like:
                    word_count += 1

            segment_ordinal += 1

    lesson.word_count = word_count
    lesson.segment_count = segment_ordinal
    lesson.status = "ready"
    await session.flush()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_import_service.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/src/flinq/modules/lesson_library/repo.py backend/src/flinq/modules/lesson_library/service.py backend/tests/modules/lesson_library/test_import_service.py
git commit -m "feat(lessons): add idempotent import service (segments + occurrences)"
```

---

## Task 6: Worker job + enqueue helper (AC#4)

**Files:**
- Modify: `backend/src/flinq/worker/tasks.py`
- Test: `backend/tests/modules/lesson_library/test_import_job.py` (create)

- [ ] **Step 1: Write the failing job tests**

Create `backend/tests/modules/lesson_library/test_import_job.py`:

```python
"""Worker job: success → ready/done, errors → failed, duplicate delivery no-op (AC#4)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.identity.repo import UserRepo
from flinq.modules.lesson_library.models import Lesson, LessonImportJob, LessonTokenOccurrence
from flinq.modules.lesson_library.repo import LessonRepo
from flinq.worker.tasks import run_lesson_import


async def _seed(session: AsyncSession, raw_text: str) -> tuple[uuid.UUID, uuid.UUID]:
    user = await UserRepo(session).create(
        email=f"job-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name="T",
        role="learner",
    )
    await session.flush()
    repo = LessonRepo(session)
    lesson = await repo.create_processing_lesson(
        owner_user_id=user.id,
        title="T",
        language_code="pt",
        raw_text=raw_text,
        visibility="private",
    )
    job = await repo.add_import_job(lesson_id=lesson.id, requested_by_user_id=user.id)
    await session.commit()
    return lesson.id, job.id


async def _occ_count(session: AsyncSession, lesson_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(LessonTokenOccurrence)
        .where(LessonTokenOccurrence.lesson_id == lesson_id)
    )
    return (await session.execute(stmt)).scalar_one()


async def test_job_success_sets_ready_and_done(db_session: AsyncSession) -> None:
    lesson_id, job_id = await _seed(db_session, "Olá mundo. Tudo bem?")

    await run_lesson_import(lesson_id, job_id)

    refreshed = await db_session.get(Lesson, lesson_id)
    job = await db_session.get(LessonImportJob, job_id)
    assert refreshed is not None and refreshed.status == "ready"
    assert job is not None and job.status == "done"
    assert job.finished_at is not None


async def test_job_failure_sets_failed_and_records_error(
    db_session: AsyncSession, monkeypatch
) -> None:
    lesson_id, job_id = await _seed(db_session, "anything")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("segmentation exploded")

    # Force the processing step to raise.
    monkeypatch.setattr("flinq.worker.tasks.process_lesson_import", _boom)

    await run_lesson_import(lesson_id, job_id)

    refreshed = await db_session.get(Lesson, lesson_id)
    job = await db_session.get(LessonImportJob, job_id)
    assert refreshed is not None and refreshed.status == "failed"
    assert job is not None and job.status == "failed"
    assert job.error_message and "segmentation exploded" in job.error_message


async def test_duplicate_delivery_is_a_noop(db_session: AsyncSession) -> None:
    """A second delivery of the same (done) job must not double the facts (review #2)."""
    lesson_id, job_id = await _seed(db_session, "Olá mundo. Tudo bem?")

    await run_lesson_import(lesson_id, job_id)
    first = await _occ_count(db_session, lesson_id)

    # Re-deliver the same job id: job is already done → guarded no-op.
    await run_lesson_import(lesson_id, job_id)

    assert await _occ_count(db_session, lesson_id) == first
    job = await db_session.get(LessonImportJob, job_id)
    assert job is not None and job.status == "done"
```

Note: the tests `commit` the seed so `run_lesson_import` (which opens its own `session_scope`) sees the rows. After `run_lesson_import`, `db_session.get` re-reads from the same DB; if SQLAlchemy returns a cached instance, call `await db_session.refresh(obj)` — but a fresh `get` after another session committed will read current DB state because `db_session` has not loaded these ids yet.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_import_job.py -v`
Expected: FAIL — `run_lesson_import` not found.

- [ ] **Step 3: Add the job, runner, and enqueue helper**

Edit `backend/src/flinq/worker/tasks.py`. Add imports near the top (after the existing imports):

```python
import uuid
from datetime import datetime, timezone

from flinq.modules.lesson_library.repo import LessonRepo
from flinq.modules.lesson_library.service import LessonNotProcessable, process_lesson_import
```

Then append the following to the file (before the `scheduler = ...` line is fine; keep `scheduler` last):

```python
async def run_lesson_import(lesson_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Process an import for an EXACT job, end-to-end. Retry/duplicate-safe.

    Plain async function so tests and a future synchronous path can call it
    without a running worker. The taskiq task simply wraps this. The job row is
    locked FOR UPDATE and only a pending/running job is run, so duplicate task
    delivery becomes a no-op instead of double-processing (review finding #2).
    """
    async with session_scope() as session:
        repo = LessonRepo(session)
        job = await repo.lock_job(job_id)  # FOR UPDATE: serialize deliveries
        if job is None:
            logger.warning("run_lesson_import: job {} not found", job_id)
            return
        if job.status not in {"pending", "running"}:
            logger.info("run_lesson_import: job {} already {}; skipping", job_id, job.status)
            return
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await session.flush()
        try:
            await process_lesson_import(session, lesson_id)
        except LessonNotProcessable as exc:
            logger.info("run_lesson_import: skipped {} ({})", lesson_id, exc)
            job.status = "done"
            job.finished_at = datetime.now(timezone.utc)
            return
        except Exception as exc:  # noqa: BLE001 - record any failure on the job
            logger.exception("run_lesson_import failed for {}", lesson_id)
            lesson = await repo.get_lesson(lesson_id)
            if lesson is not None:
                lesson.status = "failed"
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            return
        job.status = "done"
        job.finished_at = datetime.now(timezone.utc)


@broker.task
async def import_lesson_task(lesson_id: str, job_id: str) -> None:
    """Taskiq entry point: process a lesson import for an exact job."""
    await run_lesson_import(uuid.UUID(lesson_id), uuid.UUID(job_id))


async def enqueue_lesson_import(lesson_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Enqueue the import task. Patched in tests to isolate the API handler."""
    await import_lesson_task.kiq(str(lesson_id), str(job_id))
```

Important: `session_scope()` commits on successful exit and rolls back on exception. Because the failure path **catches** the exception and returns normally, the `failed` status and `error_message` are committed (not rolled back). Do not let the exception propagate out of `session_scope`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_import_job.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/flinq/worker/tasks.py backend/tests/modules/lesson_library/test_import_job.py
git commit -m "feat(lessons): add taskiq import job with ready/failed lifecycle"
```

---

## Task 7: API — async POST (202) + GET status, update existing tests (AC#3)

**Files:**
- Modify: `backend/src/flinq/modules/lesson_library/schemas.py`
- Modify: `backend/src/flinq/api/lessons.py`
- Modify: `backend/tests/api/test_lessons.py`
- Test: `backend/tests/api/test_lessons_import.py` (create)

- [ ] **Step 1: Write the failing API import test**

Create `backend/tests/api/test_lessons_import.py`:

```python
"""POST returns 202 + processing and enqueues; GET polls status (AC#3)."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


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


async def test_post_returns_202_processing_and_enqueues(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def _spy(lesson_id, job_id) -> None:
        calls.append((str(lesson_id), str(job_id)))

    monkeypatch.setattr("flinq.api.lessons.enqueue_lesson_import", _spy)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "import-202@example.com")
        r = await c.post(
            "/api/lessons",
            json={
                "title": "Olá",
                "language_code": "pt",
                "raw_text": "Olá mundo. Tudo bem?",
                "visibility": "private",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "processing"
        assert "id" in body
        # Enqueued exactly once, for the created lesson (job id is non-empty).
        assert len(calls) == 1
        assert calls[0][0] == body["id"]
        assert calls[0][1]

        # Poll endpoint returns the current status.
        r2 = await c.get(f"/api/lessons/{body['id']}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "processing"


async def test_enqueue_failure_marks_failed_and_returns_503(monkeypatch) -> None:
    """If the queue is down, the lesson must not be stranded in processing (review #1)."""

    async def _boom(lesson_id, job_id) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr("flinq.api.lessons.enqueue_lesson_import", _boom)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "import-enqueue-fail@example.com")
        r = await c.post(
            "/api/lessons",
            json={
                "title": "Stuck?",
                "language_code": "pt",
                "raw_text": "Olá mundo.",
                "visibility": "private",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 503

        # The lesson exists but is failed (not stuck in processing).
        r2 = await c.get("/api/lessons?lang=pt")
        assert r2.status_code == 200
        statuses = {item["title"]: item["status"] for item in r2.json()["items"]}
        assert statuses.get("Stuck?") == "failed"


async def test_get_unknown_lesson_returns_404(monkeypatch) -> None:
    async def _spy(lesson_id, job_id) -> None:
        return None

    monkeypatch.setattr("flinq.api.lessons.enqueue_lesson_import", _spy)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _register_and_onboard(c, "import-404@example.com")
        r = await c.get("/api/lessons/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404


async def test_get_requires_auth() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/lessons/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 401
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_lessons_import.py -v`
Expected: FAIL — POST still returns 201; `GET /api/lessons/{id}` and `enqueue_lesson_import` not wired.

- [ ] **Step 3: Add the response schemas**

In `backend/src/flinq/modules/lesson_library/schemas.py`, append:

```python
class LessonCreatedResponse(BaseModel):
    id: uuid.UUID
    status: str


class LessonStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    language_code: str
    status: str
    word_count: int
    segment_count: int
    visibility: str
    created_at: datetime
```

- [ ] **Step 4: Rewrite the lessons API**

Replace the full contents of `backend/src/flinq/api/lessons.py` with:

```python
"""Lessons API: list, async import (202 + enqueue), and status polling."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.lesson_library import service
from flinq.modules.lesson_library.repo import LessonRepo
from flinq.modules.lesson_library.schemas import (
    CreateLessonRequest,
    LessonCreatedResponse,
    LessonListResponse,
    LessonStatusResponse,
    LessonSummary,
)
from flinq.worker.tasks import enqueue_lesson_import

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


def _require_user(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user_id


@router.get("", response_model=LessonListResponse)
async def list_lessons(
    request: Request,
    lang: str,
    tab: str = "lessons",
    q: str | None = None,
    visibility: str = "all",
    page: int = 1,
    page_size: int = 25,
    session: AsyncSession = Depends(get_session),
) -> LessonListResponse:
    user_id = _require_user(request)
    items, total = await LessonRepo(session).list_for_user(
        user_id=user_id,
        lang=lang,
        q=q,
        visibility=visibility,
        tab=tab,
        page=page,
        page_size=page_size,
    )
    return LessonListResponse(
        items=[LessonSummary.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=LessonCreatedResponse)
async def create_lesson(
    body: CreateLessonRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LessonCreatedResponse:
    user_id = _require_user(request)
    lesson, job_id = await service.create_lesson_for_import(
        owner_user_id=user_id,
        title=body.title,
        language_code=body.language_code,
        raw_text=body.raw_text,
        visibility=body.visibility,
        repo=LessonRepo(session),
    )
    lesson_id = lesson.id
    # Commit so the background worker (which opens its own session) sees the rows.
    await session.commit()
    # If the queue is unavailable, do NOT strand the lesson in `processing`
    # forever (review finding #1): mark it failed and surface a 503 so the
    # client can retry, instead of a spinner that never resolves.
    try:
        await enqueue_lesson_import(lesson_id, job_id)
    except Exception as exc:  # noqa: BLE001 - any enqueue/transport failure
        logger.warning("enqueue_lesson_import failed for {}: {}", lesson_id, exc)
        await service.mark_import_failed(
            session, lesson_id=lesson_id, job_id=job_id, error=f"enqueue failed: {exc}"
        )
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "could not queue lesson import"
        ) from exc
    return LessonCreatedResponse(id=lesson_id, status=lesson.status)


@router.get("/{lesson_id}", response_model=LessonStatusResponse)
async def get_lesson(
    lesson_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LessonStatusResponse:
    user_id = _require_user(request)
    lesson = await LessonRepo(session).get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if lesson.owner_user_id != user_id and lesson.visibility != "shared":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return LessonStatusResponse.model_validate(lesson)
```

Note on the GET-before-auth ordering: `CSRFMiddleware` only guards mutating methods, so `GET /api/lessons/{id}` without a session reaches the handler and returns 401 via `_require_user` (matches `test_get_requires_auth`).

- [ ] **Step 5: Update the existing lessons tests for async behavior**

The old `test_lessons.py` asserts `201` + `ready` + `word_count` synchronously, which no longer holds. Edit `backend/tests/api/test_lessons.py`:

Replace `test_create_and_list_lesson` with a version that drives the import service directly after the 202:

```python
async def test_create_and_list_lesson() -> None:
    from flinq.core.db import session_scope
    from flinq.modules.lesson_library import service

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "lessons-create@example.com", lang="pt")

        r = await c.post(
            "/api/lessons",
            json={
                "title": "Olá mundo",
                "language_code": "pt",
                "raw_text": "Olá mundo. Como vai você?",
                "visibility": "private",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "processing"
        lesson_id = body["id"]

        # Drive processing directly (do not depend on a running worker).
        import uuid as _uuid

        async with session_scope() as s:
            await service.process_lesson_import(s, _uuid.UUID(lesson_id))

        # Status endpoint now reports ready with counts.
        r = await c.get(f"/api/lessons/{lesson_id}")
        assert r.status_code == 200
        st = r.json()
        assert st["status"] == "ready"
        assert st["word_count"] == 5

        # List for the same language includes it.
        r = await c.get("/api/lessons?lang=pt")
        assert r.status_code == 200
        titles = [item["title"] for item in r.json()["items"]]
        assert "Olá mundo" in titles
```

In the same file, the other tests still send POST and only assert auth/validation/list behavior. Two need status-code updates because POST now returns 202 instead of 201 — but they currently don't assert the POST status (they ignore it), so they keep working. Verify by reading each: `test_list_lessons_filters_by_language`, `test_list_search_by_title` POST then GET and never assert the POST code, so no change needed. `test_create_requires_auth` (expects 403 from CSRF) and `test_create_validates_language` (expects 422) and `test_list_requires_auth` (401) are unaffected. Leave them as-is.

- [ ] **Step 6: Run the API tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/test_lessons.py tests/api/test_lessons_import.py -v`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add backend/src/flinq/modules/lesson_library/schemas.py backend/src/flinq/api/lessons.py backend/tests/api/test_lessons.py backend/tests/api/test_lessons_import.py
git commit -m "feat(lessons): async import endpoint (202) + status polling"
```

---

## Task 8: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full lesson_library + lessons test suite**

Run: `cd backend && uv run pytest tests/modules/lesson_library tests/api/test_lessons.py tests/api/test_lessons_import.py -v`
Expected: all PASS.

- [ ] **Step 2: Run the entire backend test suite**

Run: `cd backend && uv run pytest -q`
Expected: all PASS. If integration tests error because Docker/Postgres testcontainers are unavailable in the environment, report that explicitly and distinguish it from real failures (do not claim green without the output).

- [ ] **Step 3: Lint and format**

Run: `cd backend && uv run ruff check . && uv run ruff format --check .`
Expected: no errors. If ruff reports auto-fixable issues only in the new files, run `uv run ruff check . --fix` and re-run; report what changed.

- [ ] **Step 4: Type check**

Run: `cd backend && uv run pyright`
Expected: no new errors in the files this plan touched. Pre-existing warnings/errors elsewhere (e.g. `core/db.py`, `tests/conftest.py`) are out of scope for FLQ-1 — note them but do not fix here.

- [ ] **Step 5: Verify the migration applies to a clean database (optional but recommended)**

The test suite builds its schema with `create_all`, so this is the only check that exercises the Alembic migration end-to-end. If you have a disposable Postgres available:

```bash
cd backend && FLINQ_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/flinq_migtest uv run alembic upgrade head
```

Expected: upgrades cleanly through `0003_lesson_pipeline`. Then `uv run alembic downgrade base` should drop everything without error. If no clean DB is available, state that this manual check was skipped.

- [ ] **Step 6: Final commit (only if Steps 3–4 changed files)**

```bash
git add -A
git commit -m "chore(lessons): lint/format fixes for pipeline"
```

---

## Acceptance Criteria Coverage

| AC | Where satisfied |
|----|-----------------|
| #1 — migration adds the four tables (+ lessons columns) | Task 1 (models + schema test), Task 2 (migration + chain test) |
| #2 — segment + tokenize with NFC/lowercase/trim/diacritics/internal marks/is_word_like for EN/RU/PT | Task 3 (tokenizer + tests), Task 4 (segmenter + EN/RU/PT tests) |
| #3 — POST returns 202 and enqueues; lesson starts `processing` | Task 5 (`create_lesson_for_import`), Task 7 (endpoint + 202 test) |
| #4 — lesson → `ready` after worker, or `failed` + `error_message` | Task 6 (`run_lesson_import` + success/failure tests) |
| #5 — uniqueness `(lesson_id, ordinal_in_lesson)` (+ segments) | Task 1 (`UniqueConstraint` + schema test), Task 5 (ordinal-ordering test) |
| #6 — tests: round-trip, EN/RU/PT segmentation, retry idempotency | Task 3/4 (segmentation), Task 5 (round-trip + idempotency) |
