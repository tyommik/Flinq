# Reader Page (FLQ-4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The core reading experience: `/learn/$lang/lessons/$lessonId` with page/sentence modes, ADR-0005 token highlighting, per-page bulk-known with undo, position resume, and on-demand persisted sentence translation — plus the persistence layer it stands on (`token_items`, `reader_positions`, `bulk_actions`, `lesson_segment_translations`).

**Architecture:** LingQ-shaped content API — the whole tokenized lesson in ONE user-independent response; a separate lightweight status map; client-side pagination. New backend module `flinq/modules/reader_state/` + `token_items` housed in `flinq/modules/vocabulary/` (FLQ-6's future home); sentence translation reuses the FLQ-3 gateway (same provider/kill-switch/audit) and persists per `(segment, target_lang)`. Frontend: `features/reader/` with Zustand store + TanStack Query.

**Tech Stack:** backend — FastAPI, SQLAlchemy 2 async, Alembic, pytest+testcontainers; frontend — React 19 + TS strict, TanStack Router/Query, Zustand, Tailwind v4, Vitest + @testing-library/react.

**Spec:** `.superpowers/specs/2026-07-05-reader-page-design.md` — read it first; decisions there are binding.

## Global Constraints

- Branch: `feature/FLQ-4-reader-page` off current `main`.
- Backend gates after every backend task (from `backend/`): `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` (0 errors), `uv run pytest`.
- Frontend gates after every frontend task (from `frontend/`): `pnpm exec tsc -b --noEmit 2>/dev/null || pnpm exec tsc --noEmit`, `pnpm exec eslint .`, `pnpm exec vitest run`, `pnpm exec vite build`. (Use `corepack pnpm` if bare `pnpm` is unavailable.)
- Commits (AGENTS.md): `feat(FLQ-4.<task#>): <english imperative subject, ≤72 chars>`; body = why; scoped paths `git commit -m "..." -- <exact paths>`; NO Co-Authored-By.
- Do NOT edit `README.md`, `docs/adr/*`, `.github/workflows/*`, `backend/Dockerfile`, `AGENTS.md` — uncommitted user WIP.
- Join-key invariant: `token_items.token_text` stores `normalize_token` output; the reader NEVER re-normalizes — it matches occurrences' stored `normalized_text` verbatim.
- ADR-0005 invariants: absent row = `new`; bulk-known touches ONLY `new`; undo required; statuses limited to `tracked|known|ignored`.
- UNICODE: tests contain Cyrillic and accented Portuguese; copy byte-exactly (project was burned twice); sanity-grep after writing.
- New backend code: `from __future__ import annotations`, full annotations, `Mapped[...]`. New frontend code: TS strict, existing import style (`@/` alias).

---

### Task 0: Branch

- [ ] **Step 1:**

```bash
git checkout main && git pull --ff-only && git checkout -b feature/FLQ-4-reader-page
```

---

### Task 1: Models + migration 0006

**Files:**
- Create: `backend/src/flinq/modules/vocabulary/__init__.py` (docstring `"""Vocabulary: per-user learning items (FLQ-4 ships token_items; FLQ-6 builds the rest)."""`), `backend/src/flinq/modules/vocabulary/models.py`
- Create: `backend/src/flinq/modules/reader_state/__init__.py` (docstring `"""Reader state: positions, bulk actions, content assembly, segment translations (FLQ-4)."""`), `backend/src/flinq/modules/reader_state/models.py`
- Create: `backend/migrations/versions/0006_reader_state.py`
- Test: `backend/tests/modules/reader_state/__init__.py` (empty), `backend/tests/modules/reader_state/test_models_schema.py`
- Modify: `backend/tests/conftest.py` (`_init_schema`: add side-effect imports for `vocabulary.models` and `reader_state.models` next to the existing four)

**Interfaces:**
- Produces: `TokenItem` (vocabulary), `ReaderPosition`, `BulkAction`, `LessonSegmentTranslation` (reader_state) with the exact fields below. Tasks 3–6 depend on these names.

- [ ] **Step 1: Write the failing tests**

`backend/tests/modules/reader_state/test_models_schema.py`:

```python
"""Schema invariants: token_items uniqueness + confidence checks, position upsert key."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.identity.repo import UserRepo
from flinq.modules.reader_state.models import ReaderPosition
from flinq.modules.vocabulary.models import TokenItem


@pytest.fixture(autouse=True)
async def _clean(db_session: AsyncSession) -> None:
    yield
    await db_session.execute(delete(TokenItem))
    await db_session.execute(delete(ReaderPosition))
    await db_session.commit()


async def _user(db_session: AsyncSession) -> uuid.UUID:
    user = await UserRepo(db_session).create(
        email=f"rs-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name="T",
        role="learner",
    )
    await db_session.flush()
    return user.id


def _item(user_id: uuid.UUID, **kw: object) -> TokenItem:
    base: dict[str, object] = {
        "user_id": user_id,
        "language_code": "pt",
        "token_text": "edifício",
        "status": "known",
        "confidence": None,
    }
    base.update(kw)
    return TokenItem(**base)  # type: ignore[arg-type]


async def test_token_item_unique_per_user_lang_text(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    db_session.add(_item(user_id))
    await db_session.flush()
    db_session.add(_item(user_id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_tracked_requires_confidence_and_known_forbids_it(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    db_session.add(_item(user_id, token_text="a", status="tracked", confidence=None))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
    user_id = await _user(db_session)
    db_session.add(_item(user_id, token_text="b", status="known", confidence=3))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
    user_id = await _user(db_session)
    db_session.add(_item(user_id, token_text="c", status="tracked", confidence=2))
    await db_session.flush()


async def test_reader_position_unique_per_user_lesson(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    from flinq.modules.lesson_library.repo import LessonRepo

    lesson = await LessonRepo(db_session).create_processing_lesson(
        owner_user_id=user_id, title="T", language_code="pt", raw_text="Olá.", visibility="private"
    )
    await db_session.flush()
    db_session.add(ReaderPosition(user_id=user_id, lesson_id=lesson.id, view_mode="page"))
    await db_session.flush()
    db_session.add(ReaderPosition(user_id=user_id, lesson_id=lesson.id, view_mode="sentence"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

- [ ] **Step 2: Run to verify failure** (`uv run pytest tests/modules/reader_state/ -v` → ModuleNotFoundError)

- [ ] **Step 3: Implement `vocabulary/models.py`**

```python
"""Per-user vocabulary items (domain model §8.2).

`token_text` is stored ALREADY NORMALIZED (flinq.core.textnorm.normalize_token
output) — it is the join key to lesson occurrences and dictionary headwords.
No FK to occurrences (§2.4): the link is computed by
(user_id, lesson.language_code, normalized_text).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from flinq.core.db import Base


class TokenItem(Base):
    __tablename__ = "token_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    language_code: Mapped[str] = mapped_column(String(8))
    token_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # tracked | known | ignored ('new' is computed)
    confidence: Mapped[int | None] = mapped_column(Integer)
    created_from_occurrence_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "language_code", "token_text", name="uq_token_items_user_lang_text"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 5)",
            name="ck_token_items_confidence_range",
        ),
        CheckConstraint(
            "(status = 'tracked') = (confidence IS NOT NULL)",
            name="ck_token_items_confidence_tracked",
        ),
        Index("ix_token_items_user_lang", "user_id", "language_code"),
    )
```

- [ ] **Step 4: Implement `reader_state/models.py`**

```python
"""Reader state persistence (domain model §7.1-7.2) + segment translations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from flinq.core.db import Base


class ReaderPosition(Base):
    __tablename__ = "reader_positions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    view_mode: Mapped[str] = mapped_column(String(16), default="page")  # page | sentence
    current_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    current_token_ordinal: Mapped[int | None] = mapped_column()
    last_opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "lesson_id", name="uq_reader_positions_user_lesson"),)


class BulkAction(Base):
    __tablename__ = "bulk_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    action_type: Mapped[str] = mapped_column(String(32), default="bulk_known")
    page_fingerprint: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LessonSegmentTranslation(Base):
    __tablename__ = "lesson_segment_translations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    segment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lesson_segments.id", ondelete="CASCADE"))
    target_language_code: Mapped[str] = mapped_column(String(8))
    translation_text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="ai")
    model: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("segment_id", "target_language_code", name="uq_segment_translation_lang"),
    )
```

- [ ] **Step 5: conftest side-effect imports** (both new modules, same noqa/pyright pattern as the existing four)

- [ ] **Step 6: Run tests to verify pass** (3 tests)

- [ ] **Step 7: Migration `0006_reader_state.py`** — `revision = "0006_reader_state"`, `down_revision = "0005_ai_requests"`; mirror the four models 1:1 in `0005` style (named CheckConstraints via `sa.CheckConstraint(..., name=...)` inside `op.create_table`); downgrade drops in reverse order (lesson_segment_translations, bulk_actions, reader_positions, token_items). Verify: `uv run pytest tests/modules/lesson_library/test_migration_chain.py -v` → PASS.

- [ ] **Step 8: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
git add backend/src/flinq/modules/vocabulary backend/src/flinq/modules/reader_state backend/migrations/versions/0006_reader_state.py backend/tests/modules/reader_state backend/tests/conftest.py
git commit -m "feat(FLQ-4.1): add token_items and reader state models with migration" -- backend/src/flinq/modules/vocabulary backend/src/flinq/modules/reader_state backend/migrations/versions/0006_reader_state.py backend/tests/modules/reader_state backend/tests/conftest.py
```

---

### Task 2: Content endpoint (`GET /api/lessons/{id}/content`)

**Files:**
- Create: `backend/src/flinq/modules/reader_state/content.py` (pure-ish assembly), `backend/src/flinq/modules/reader_state/schemas.py` (content part), `backend/src/flinq/api/reader.py` (router, content route first)
- Modify: `backend/src/flinq/main.py` (register `reader_router` after `lessons_router`; add `GZipMiddleware`)
- Test: `backend/tests/api/test_reader_content.py`

**Interfaces:**
- Produces: router `flinq.api.reader:router` (prefix `/api`); `_get_readable_lesson(session, lesson_id, user_id) -> Lesson` helper in `flinq/modules/reader_state/access.py` (create it here; raises `LessonNotFound` / `LessonForbidden` module exceptions mapped to 404/403 in the router) — Tasks 3–6 reuse it.
- Response schema (short keys are the wire contract, spec §API-1):

```python
# schemas.py (content part)
class WordToken(BaseModel):
    t: str
    n: str
    i: int

class WhitespaceToken(BaseModel):
    ws: str

class PunctToken(BaseModel):
    p: str

Token = WordToken | WhitespaceToken | PunctToken

class SentenceOut(BaseModel):
    seg_id: uuid.UUID
    index: int                      # sentence ordinal (segment.ordinal)
    text: str
    normalized_text: str
    tokens: list[Token]

class ParagraphOut(BaseModel):
    sentences: list[SentenceOut]

class LessonContentResponse(BaseModel):
    lesson_id: uuid.UUID
    language_code: str
    word_count: int
    paragraphs: list[ParagraphOut]
```

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_reader_content.py` — self-contained; copy the `_register_and_onboard` helper (as in `test_dictionary_lookup.py`), create a lesson via `POST /api/lessons` with enqueue stubbed to run import inline (pattern from `tests/api/test_lessons.py::test_create_and_list_lesson`: stub `flinq.api.lessons.enqueue_lesson_import` with a no-op, then call `flinq.modules.lesson_library.service.process_lesson_import(session, lesson_id)` directly via `session_scope`). Fixture text (genuine Portuguese/Cyrillic-free, two paragraphs):

```python
TEXT = "O edifício antigo fica na praça. Eu gosto dele.\n\nSegundo parágrafo aqui."
```

Tests:

```python
async def test_content_shape_and_reconstruction(db_session, monkeypatch) -> None:
    # create+process lesson, GET /api/lessons/{id}/content
    # assert: 2 paragraphs; first has 2 sentences; word_count == 13
    # reconstruction fidelity: for every sentence, "".join(piece) == sentence.text
    #   where piece = tok.t | tok.ws | tok.p in order
    # global ordinals strictly increasing across the whole lesson

async def test_content_requires_auth() -> None:
    # no session -> 401

async def test_content_foreign_private_403_unknown_404(db_session, monkeypatch) -> None:
    # second user gets 403 on first user's private lesson; random uuid -> 404

async def test_content_processing_lesson_409(db_session, monkeypatch) -> None:
    # lesson still processing (enqueue stubbed, import NOT run) -> 409 {"detail": "lesson_not_ready"}
```

Write them as real code (follow `test_lessons.py` inline-import pattern); assert `word_count == 13` (11 words in paragraph 1: O, edifício, antigo, fica, na, praça, Eu, gosto, dele + 3 in paragraph 2: Segundo, parágrafo, aqui — recount when writing: the exact number the fixture yields; pin the number after first GREEN run and assert it, don't leave it symbolic).

- [ ] **Step 2: Run to verify failure** (404 route)

- [ ] **Step 3: Implement**

`reader_state/access.py`:

```python
"""Lesson access rule shared by all reader endpoints."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import Lesson


class LessonNotFound(Exception): ...


class LessonForbidden(Exception): ...


class LessonNotReady(Exception): ...


async def get_readable_lesson(
    session: AsyncSession, lesson_id: uuid.UUID, user_id: uuid.UUID, *, require_ready: bool = True
) -> Lesson:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise LessonNotFound
    if lesson.visibility != "shared" and lesson.owner_user_id != user_id:
        raise LessonForbidden
    if require_ready and lesson.status != "ready":
        raise LessonNotReady
    return lesson
```

`reader_state/content.py`:

```python
"""Assemble the LingQ-shaped tokenized lesson content (spec API-1).

User-independent: built purely from lesson facts. Whitespace tokens are the
raw_text gaps between consecutive occurrences inside a sentence, so
concatenating the stream reproduces the sentence text byte-for-byte.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.lesson_library.models import Lesson, LessonSegment, LessonTokenOccurrence
from flinq.modules.reader_state.schemas import (
    LessonContentResponse,
    ParagraphOut,
    PunctToken,
    SentenceOut,
    Token,
    WhitespaceToken,
    WordToken,
)


async def build_lesson_content(session: AsyncSession, lesson: Lesson) -> LessonContentResponse:
    segments = list(
        (
            await session.scalars(
                select(LessonSegment)
                .where(LessonSegment.lesson_id == lesson.id)
                .order_by(LessonSegment.ordinal)
            )
        ).all()
    )
    occurrences = list(
        (
            await session.scalars(
                select(LessonTokenOccurrence)
                .where(LessonTokenOccurrence.lesson_id == lesson.id)
                .order_by(LessonTokenOccurrence.ordinal_in_lesson)
            )
        ).all()
    )
    by_segment: dict[object, list[LessonTokenOccurrence]] = {}
    for occ in occurrences:
        by_segment.setdefault(occ.segment_id, []).append(occ)

    word_count = sum(1 for occ in occurrences if occ.is_word_like)
    paragraphs = [s for s in segments if s.segment_type == "paragraph"]
    sentences = [s for s in segments if s.segment_type == "sentence"]

    def tokens_for(sentence: LessonSegment) -> list[Token]:
        out: list[Token] = []
        pos = sentence.start_char_offset
        for occ in by_segment.get(sentence.id, []):
            if occ.start_char_offset > pos:
                out.append(WhitespaceToken(ws=lesson.raw_text[pos : occ.start_char_offset]))
            if occ.is_word_like:
                out.append(WordToken(t=occ.surface_text, n=occ.normalized_text, i=occ.ordinal_in_lesson))
            else:
                out.append(PunctToken(p=occ.surface_text))
            pos = occ.end_char_offset
        if pos < sentence.end_char_offset:
            out.append(WhitespaceToken(ws=lesson.raw_text[pos : sentence.end_char_offset]))
        return out

    para_out: list[ParagraphOut] = []
    for para in paragraphs:
        inner = [
            SentenceOut(
                seg_id=s.id,
                index=s.ordinal,
                text=s.text,
                normalized_text=s.text.lower(),
                tokens=tokens_for(s),
            )
            for s in sentences
            if para.start_char_offset <= s.start_char_offset and s.end_char_offset <= para.end_char_offset
        ]
        para_out.append(ParagraphOut(sentences=inner))
    return LessonContentResponse(
        lesson_id=lesson.id,
        language_code=lesson.language_code,
        word_count=word_count,
        paragraphs=para_out,
    )
```

Note: `normalized_text` of a sentence = simple `.lower()` of the sentence text (it is display/AI-context material, NOT the token join key — do not run `normalize_token` on whole sentences).

`api/reader.py` — router (prefix `/api`, tags `["reader"]`), `_require_user` copied verbatim from `api/dictionary.py`; route:

```python
@router.get("/lessons/{lesson_id}/content", response_model=LessonContentResponse)
async def lesson_content(...):
    user_id = _require_user(request)
    try:
        lesson = await get_readable_lesson(session, lesson_id, user_id)
    except LessonNotFound:
        raise HTTPException(404) from None
    except LessonForbidden:
        raise HTTPException(403) from None
    except LessonNotReady:
        raise HTTPException(409, detail="lesson_not_ready") from None
    return await build_lesson_content(session, lesson)
```

`main.py`: `from fastapi.middleware.gzip import GZipMiddleware`; `app.add_middleware(GZipMiddleware, minimum_size=1024)` (add BEFORE the CSRF/Session middlewares in code order — Starlette wraps in reverse, gzip must be innermost of the three, i.e. added first); `from flinq.api.reader import router as reader_router`; `app.include_router(reader_router)` after lessons.

- [ ] **Step 4: Run to verify pass, then full suite**
- [ ] **Step 5: Gates + commit**

```bash
git add backend/src/flinq/modules/reader_state/content.py backend/src/flinq/modules/reader_state/schemas.py backend/src/flinq/modules/reader_state/access.py backend/src/flinq/api/reader.py backend/src/flinq/main.py backend/tests/api/test_reader_content.py
git commit -m "feat(FLQ-4.2): add tokenized lesson content endpoint with gzip" -- backend/src/flinq/modules/reader_state/content.py backend/src/flinq/modules/reader_state/schemas.py backend/src/flinq/modules/reader_state/access.py backend/src/flinq/api/reader.py backend/src/flinq/main.py backend/tests/api/test_reader_content.py
```

---

### Task 3: Token statuses endpoint

**Files:**
- Create: `backend/src/flinq/modules/reader_state/statuses.py`
- Modify: `backend/src/flinq/modules/reader_state/schemas.py` (add), `backend/src/flinq/api/reader.py` (add route)
- Test: `backend/tests/api/test_reader_statuses.py`

**Interfaces:**
- `GET /api/lessons/{id}/token-statuses` → `{"statuses": {"<normalized>": {"s": "tracked", "c": 2}}}` (`c` omitted/None unless tracked). Schema: `TokenStatusOut(s: str, c: int | None = None)`, `TokenStatusesResponse(statuses: dict[str, TokenStatusOut])`.
- `statuses.py`: `async def lesson_token_statuses(session, *, lesson: Lesson, user_id) -> dict[str, TokenStatusOut]` — one query: `select TokenItem.token_text, status, confidence where user_id=..., language_code=lesson.language_code AND token_text IN (select distinct normalized_text from occurrences where lesson_id=... and is_word_like)`.

- [ ] **Step 1: Failing tests** (`test_reader_statuses.py`): seed lesson (same helper as Task 2); insert `TokenItem`s directly via `db_session` (one `known` for a word in the lesson, one `tracked` c=2, one item for a word NOT in the lesson, one item in another language); assert response contains exactly the two in-lesson entries with right shapes; auth 401; empty map for fresh user.
- [ ] **Step 2: RED → implement → GREEN → full suite**
- [ ] **Step 3: Gates + commit** — `feat(FLQ-4.3): add per-lesson token statuses endpoint` scoped to statuses.py, schemas.py, api/reader.py, test file.

---

### Task 4: Reader positions (PUT upsert + lesson GET extension)

**Files:**
- Create: `backend/src/flinq/modules/reader_state/positions.py`
- Modify: `backend/src/flinq/modules/reader_state/schemas.py`, `backend/src/flinq/api/reader.py`, `backend/src/flinq/api/lessons.py` + `backend/src/flinq/modules/lesson_library/schemas.py` (extend `LessonStatusResponse` with `reader_position: ReaderPositionOut | None = None`)
- Test: `backend/tests/api/test_reader_positions.py`

**Interfaces:**
- `PUT /api/reader/positions` body `{lesson_id, view_mode: Literal["page","sentence"], current_segment_id: UUID|None, current_token_ordinal: int|None}` → 204. Access-checked via `get_readable_lesson(require_ready=False)`.
- `positions.py`: `upsert_position(...)` via `sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_update(index_elements=["user_id","lesson_id"], set_={view_mode, current_segment_id, current_token_ordinal, last_opened_at: func.now()})`; `get_position(session, user_id, lesson_id) -> ReaderPosition | None`.
- `api/lessons.py::get_lesson`: after loading the lesson, fetch position and attach: `resp = LessonStatusResponse.model_validate(lesson); resp.reader_position = ReaderPositionOut.model_validate(pos) if pos else None`. `ReaderPositionOut(view_mode, current_segment_id, current_token_ordinal)` (from_attributes).

- [ ] **Step 1: Failing tests**: PUT creates row (204, GET lesson returns it); second PUT updates same row (no duplicate — assert count 1 and new values); PUT for foreign private lesson → 403; unauthenticated → 403 (CSRF intercepts bare PUT — same platform behavior as FLQ-3; comment it).
- [ ] **Step 2: RED → implement → GREEN → full suite**
- [ ] **Step 3: Gates + commit** — `feat(FLQ-4.4): add reader position upsert and lesson resume field` scoped to positions.py, schemas.py, api/reader.py, api/lessons.py, lesson_library/schemas.py, test file.

---

### Task 5: Bulk-known + undo

**Files:**
- Create: `backend/src/flinq/modules/reader_state/bulk.py`
- Modify: `backend/src/flinq/modules/reader_state/schemas.py`, `backend/src/flinq/api/reader.py`
- Test: `backend/tests/api/test_reader_bulk.py`

**Interfaces:**
- `POST /api/reader/bulk-known` `{lesson_id, from_ordinal: int>=0, to_ordinal: int>=from}` → `{action_id, created_count}`.
- `POST /api/reader/bulk-actions/{action_id}/undo` → `{undone_count}`; 404 foreign/unknown action; 409 already undone.
- `bulk.py`:

```python
async def bulk_mark_known(session, *, user_id, lesson, from_ordinal, to_ordinal):
    texts = set(await session.scalars(
        select(LessonTokenOccurrence.normalized_text).distinct().where(
            LessonTokenOccurrence.lesson_id == lesson.id,
            LessonTokenOccurrence.is_word_like.is_(True),
            LessonTokenOccurrence.ordinal_in_lesson.between(from_ordinal, to_ordinal),
        )))
    if texts:
        stmt = (pg_insert(TokenItem)
            .values([{"id": uuid.uuid4(), "user_id": user_id, "language_code": lesson.language_code,
                      "token_text": t, "status": "known", "confidence": None} for t in sorted(texts)])
            .on_conflict_do_nothing(constraint="uq_token_items_user_lang_text")
            .returning(TokenItem.id))
        created_ids = list((await session.execute(stmt)).scalars().all())
    else:
        created_ids = []
    action = BulkAction(user_id=user_id, lesson_id=lesson.id, action_type="bulk_known",
                        page_fingerprint=f"{from_ordinal}:{to_ordinal}",
                        payload_json={"token_item_ids": [str(i) for i in created_ids]})
    session.add(action); await session.commit()
    return action.id, len(created_ids)

async def undo_bulk_action(session, *, user_id, action_id):
    action = await session.get(BulkAction, action_id)
    if action is None or action.user_id != user_id: raise ActionNotFound
    if action.undone_at is not None: raise ActionAlreadyUndone
    ids = [uuid.UUID(x) for x in action.payload_json.get("token_item_ids", [])]
    undone = 0
    if ids:
        result = await session.execute(
            delete(TokenItem).where(TokenItem.id.in_(ids), TokenItem.status == "known")
            .returning(TokenItem.id))
        undone = len(list(result.scalars().all()))
    action.undone_at = func.now()
    await session.commit()
    return undone
```

(ON CONFLICT insert with explicit client-side UUIDs so `.returning` yields only genuinely-inserted rows.)

- [ ] **Step 1: Failing tests** (`test_reader_bulk.py`, seed lesson via Task-2 helper — extract the seeding helper into `backend/tests/api/_reader_helpers.py` now and refactor Tasks 2–4 test files to import it if they duplicated it):
  - bulk over full range → creates rows for exactly the distinct new word-like texts; statuses endpoint now reports them `known`;
  - a pre-existing `tracked` item is untouched (ADR-0005) and NOT in payload;
  - repeat bulk over same range → `created_count == 0`, no duplicates;
  - undo → items deleted, statuses map drops them; second undo → 409;
  - undo after one item was manually flipped to `tracked` (update row in-test) → that item survives, `undone_count == n-1`;
  - foreign action id → 404.
- [ ] **Step 2: RED → implement → GREEN → full suite**
- [ ] **Step 3: Gates + commit** — `feat(FLQ-4.5): add page bulk-known with undo` scoped to bulk.py, schemas.py, api/reader.py, tests/api/test_reader_bulk.py, tests/api/_reader_helpers.py (+ the refactored test files if touched).

---

### Task 6: Sentence translation (persisted, via FLQ-3 gateway)

**Files:**
- Modify: `backend/src/flinq/modules/ai_translation/prompts.py` (+`SENTENCE_SYSTEM_PROMPT`, `build_sentence_prompt`), `backend/src/flinq/modules/ai_translation/service.py` (+`translate_sentence`, extract shared audit helper), `backend/src/flinq/modules/reader_state/schemas.py`, `backend/src/flinq/api/reader.py`
- Create: `backend/src/flinq/modules/reader_state/translations.py`
- Test: `backend/tests/modules/ai_translation/test_sentence_prompt.py`, `backend/tests/api/test_segment_translation.py`

**Interfaces:**
- `ai_translation.prompts`: `SENTENCE_SYSTEM_PROMPT = "You are a translation assistant inside a language-learning reader. Reply with the translation of the given sentence only — no explanations, no quotes."`; `build_sentence_prompt(*, sentence_text: str, target_language_code: str) -> tuple[str, str]` (user msg: `f"Sentence: {normalize_ai_text(sentence_text)}\nTranslate this sentence into {LANGUAGE_NAMES[target_language_code]}."`).
- `ai_translation.service`: `translate_sentence(session, *, user_id, sentence_text, target_language_code, lesson_id=None, provider=None) -> SentenceTranslationResult` (`SentenceTranslationResult(text: str, model: str, latency_ms: int)` frozen dataclass). Same lifecycle as `translate_hints`: kill-switch → provider → `completion.text.strip()` (empty → `AIEmptyResponse`) → audit row (same taxonomy). REFACTOR RULE: extract the duplicated audit closure into a module-level `async def _write_audit(session, *, request_id, user_id, lesson_id, prompt_hash, selected_text_hash, started, settings, success, error_code, input_tokens=None, output_tokens=None)` used by BOTH `translate_hints` and `translate_sentence`; all existing FLQ-3 tests must pass UNCHANGED.
- `POST /api/lessons/{lesson_id}/segments/{segment_id}/translation` body `{target_language_code: Literal["en","ru","pt"]}` → `{text, source, model, stored: bool}`. Logic (`translations.py`): access-check lesson; verify segment belongs to lesson (else 404); stored row → return `stored=True`; else call `translate_sentence` (map `AIDisabled`→503 `ai_disabled`, provider errors→502 `ai_provider_error`, empty→502 `ai_empty_response`); insert `LessonSegmentTranslation` guarding the unique constraint (on `IntegrityError` → rollback & return the row the concurrent writer stored); return `stored=False`.

- [ ] **Step 1: Failing tests**
  - `test_sentence_prompt.py` (pure): prompt deterministic; contains sentence + target name; whitespace-normalized.
  - `test_segment_translation.py` (API, fake provider monkeypatched via `service._default_provider`): first call returns `stored=False` + text "Старое здание." and creates the row; second call returns `stored=True` and provider was NOT called again (count on the fake); AI disabled + not stored → 503; AI disabled + stored → 200 stored=True (no AI needed); segment from another lesson → 404; unauthenticated POST → 403 (CSRF).
- [ ] **Step 2: RED → implement → GREEN → full suite** (145+ tests still green — the FLQ-3 refactor must not change behavior)
- [ ] **Step 3: Gates + commit** — `feat(FLQ-4.6): add persisted on-demand sentence translation` scoped to the six files above.

---

### Task 7: Frontend API layer + pagination + store

**Files:**
- Create: `frontend/src/api/reader.ts`, `frontend/src/features/reader/pagination.ts`, `frontend/src/features/reader/readerStore.ts`
- Modify: `frontend/src/api/lessons.ts` (add `get(id)` + `LessonDetail` with `reader_position`)
- Test: `frontend/src/features/reader/pagination.test.ts`

**Interfaces (consumed by Tasks 8–11):**

`api/reader.ts`:

```ts
import { api } from './client'

export interface WordToken { t: string; n: string; i: number }
export interface WhitespaceToken { ws: string }
export interface PunctToken { p: string }
export type Token = WordToken | WhitespaceToken | PunctToken
export const isWord = (tok: Token): tok is WordToken => 't' in tok

export interface Sentence { seg_id: string; index: number; text: string; normalized_text: string; tokens: Token[] }
export interface Paragraph { sentences: Sentence[] }
export interface LessonContent { lesson_id: string; language_code: string; word_count: number; paragraphs: Paragraph[] }

export type TokenStatus = 'tracked' | 'known' | 'ignored'
export interface TokenStatusEntry { s: TokenStatus; c?: number | null }
export type StatusMap = Record<string, TokenStatusEntry>

export interface ReaderPosition { view_mode: 'page' | 'sentence'; current_segment_id: string | null; current_token_ordinal: number | null }
export interface BulkKnownResult { action_id: string; created_count: number }
export interface SegmentTranslation { text: string; source: string; model: string; stored: boolean }

export const readerApi = {
  content: (lessonId: string) => api<LessonContent>(`/api/lessons/${lessonId}/content`),
  statuses: (lessonId: string) =>
    api<{ statuses: StatusMap }>(`/api/lessons/${lessonId}/token-statuses`).then((r) => r.statuses),
  putPosition: (body: { lesson_id: string } & ReaderPosition) =>
    api<void>('/api/reader/positions', { method: 'PUT', body: JSON.stringify(body) }),
  bulkKnown: (body: { lesson_id: string; from_ordinal: number; to_ordinal: number }) =>
    api<BulkKnownResult>('/api/reader/bulk-known', { method: 'POST', body: JSON.stringify(body) }),
  undoBulk: (actionId: string) =>
    api<{ undone_count: number }>(`/api/reader/bulk-actions/${actionId}/undo`, { method: 'POST' }),
  segmentTranslation: (lessonId: string, segId: string, target: string) =>
    api<SegmentTranslation>(`/api/lessons/${lessonId}/segments/${segId}/translation`, {
      method: 'POST',
      body: JSON.stringify({ target_language_code: target }),
    }),
}
```

`pagination.ts` (pure, unit-tested):

```ts
import { isWord, type Paragraph, type Sentence } from '@/api/reader'

export interface PageSlice {
  sentences: { paragraphIndex: number; sentence: Sentence }[]
  fromOrdinal: number
  toOrdinal: number
  wordCount: number
}

export const PAGE_SIZE_WORDS = 250

export function paginate(paragraphs: Paragraph[], pageSize: number = PAGE_SIZE_WORDS): PageSlice[] {
  const flat = paragraphs.flatMap((p, paragraphIndex) =>
    p.sentences.map((sentence) => ({ paragraphIndex, sentence })),
  )
  const pages: PageSlice[] = []
  let current: PageSlice | null = null
  for (const entry of flat) {
    const words = entry.sentence.tokens.filter(isWord)
    if (!current) current = { sentences: [], fromOrdinal: Infinity, toOrdinal: -1, wordCount: 0 }
    current.sentences.push(entry)
    if (words.length > 0) {
      current.fromOrdinal = Math.min(current.fromOrdinal, words[0]!.i)
      current.toOrdinal = Math.max(current.toOrdinal, words[words.length - 1]!.i)
      current.wordCount += words.length
    }
    if (current.wordCount >= pageSize) {
      pages.push(current)
      current = null
    }
  }
  if (current && current.sentences.length > 0) pages.push(current)
  return pages
}

export function pageIndexForOrdinal(pages: PageSlice[], ordinal: number | null): number {
  if (ordinal == null) return 0
  const idx = pages.findIndex((p) => ordinal >= p.fromOrdinal && ordinal <= p.toOrdinal)
  return idx === -1 ? 0 : idx
}
```

`readerStore.ts` (Zustand + persist for font prefs only):

```ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ViewMode = 'page' | 'sentence'

interface FontPrefs { size: 0 | 1 | 2; lineHeight: 0 | 1 | 2; serif: boolean }

interface ReaderState {
  mode: ViewMode
  pageIndex: number
  sentenceFlatIndex: number
  sidebarOpen: boolean
  lastBulkActionId: string | null
  font: FontPrefs
  setMode: (m: ViewMode) => void
  setPageIndex: (i: number) => void
  setSentenceFlatIndex: (i: number) => void
  toggleSidebar: () => void
  setLastBulkActionId: (id: string | null) => void
  setFont: (f: Partial<FontPrefs>) => void
}

export const useReaderStore = create<ReaderState>()(
  persist(
    (set) => ({
      mode: 'page',
      pageIndex: 0,
      sentenceFlatIndex: 0,
      sidebarOpen: false,
      lastBulkActionId: null,
      font: { size: 1, lineHeight: 1, serif: false },
      setMode: (mode) => set({ mode }),
      setPageIndex: (pageIndex) => set({ pageIndex }),
      setSentenceFlatIndex: (sentenceFlatIndex) => set({ sentenceFlatIndex }),
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setLastBulkActionId: (lastBulkActionId) => set({ lastBulkActionId }),
      setFont: (f) => set((s) => ({ font: { ...s.font, ...f } })),
    }),
    { name: 'flinq-reader-prefs', partialize: (s) => ({ font: s.font }) as Partial<ReaderState> },
  ),
)
```

`lessons.ts` additions: `LessonDetail = LessonSummary & { segment_count: number; reader_position: ReaderPosition | null }`; `get: (id: string) => api<LessonDetail>(`/api/lessons/${id}`)`.

- [ ] **Step 1: Write failing `pagination.test.ts`**: 600 evenly-worded sentences → pages of ≥250 words each, boundaries sentence-aligned; single 900-word sentence → one page; ordinals ranges non-overlapping ascending; `pageIndexForOrdinal` hits the right page and falls back to 0.
- [ ] **Step 2: RED → implement all files → GREEN** (`pnpm exec vitest run`)
- [ ] **Step 3: Frontend gates + commit** — `feat(FLQ-4.7): add reader api client, pagination and store` scoped to the five files.

---

### Task 8: Route, lesson states, reader shell

**Files:**
- Create: `frontend/src/routes/learn.$lang.lessons.$lessonId.tsx`, `frontend/src/features/reader/ReaderPage.tsx`, `frontend/src/features/reader/ReaderTopBar.tsx`, `frontend/src/features/reader/BottomToolbar.tsx`, `frontend/src/features/reader/useReaderQueries.ts`
- Modify: `frontend/src/routeTree.ts` (register as child of `learnLangRoute`)
- Test: `frontend/src/features/reader/ReaderPage.test.tsx`

**Content:**
- Route follows the `learn.$lang.library.tsx` pattern (`createRoute`, `getParentRoute: () => learnLangRoute`, `path: 'lessons/$lessonId'`).
- `useReaderQueries.ts`: `useLessonDetail(id)` (poll `refetchInterval: (q) => q.state.data?.status === 'processing' ? 2000 : false`); `useLessonContent(id, enabled)` (`staleTime: Infinity, gcTime: Infinity`); `useTokenStatuses(id, enabled)`; mutations for position/bulk/undo/translation with `queryClient.invalidateQueries({queryKey: ['reader-statuses', id]})` on bulk/undo success.
- `ReaderPage`: statuses of the lesson: `processing` → centered spinner + «Урок готовится…» (poll); `failed` → error + «в библиотеку»; `ready` → load content+statuses, restore position (`pageIndexForOrdinal`), render TopBar + active view + BottomToolbar. Skeleton while content loads.
- `ReaderTopBar`: `[X]`→`navigate({to: '/learn/$lang/library'})`, progress `%` from bookmark ordinal / word_count, `[Aa]` popover (radix dropdown-menu with three size buttons, three line-heights, serif toggle → `setFont`), sidebar toggle (page mode only).
- `BottomToolbar`: mode toggle button («Show sentence by sentence» / «Show full page»), disabled «Review» button with title="Скоро (FLQ-7)".
- Font prefs applied as inline style/classes on the text container (`text-base|lg|xl`, `leading-normal|relaxed|loose`, `font-serif` toggle).
- Test (`ReaderPage.test.tsx`, mock `readerApi`/`lessonsApi` with `vi.mock`): processing lesson renders «Урок готовится»; ready lesson renders text words; failed renders error state.

- [ ] Steps: failing test → implement → green → gates → commit `feat(FLQ-4.8): add reader route, shell and lesson states` (scoped to the six files + routeTree.ts).

---

### Task 9: PageView + TokenSpan + word card placeholder

**Files:**
- Create: `frontend/src/features/reader/TokenSpan.tsx`, `frontend/src/features/reader/PageView.tsx`, `frontend/src/features/reader/WordCardPlaceholder.tsx`
- Modify: `frontend/src/styles/globals.css` (add `--reader-new-bg: #e0f2fe; --reader-tracked-bg: #fef08a;` to `:root` and dark-theme equivalents if a dark block exists), `frontend/src/features/reader/ReaderPage.tsx` (wire)
- Test: `frontend/src/features/reader/TokenSpan.test.tsx`

**Content:**

`TokenSpan.tsx` (memoized):

```tsx
import { memo } from 'react'
import { isWord, type Token, type TokenStatusEntry } from '@/api/reader'

interface Props {
  token: Token
  status?: TokenStatusEntry
  onWordClick?: (word: { t: string; n: string; i: number }) => void
}

export const TokenSpan = memo(function TokenSpan({ token, status, onWordClick }: Props) {
  if ('ws' in token) return <span>{token.ws}</span>
  if ('p' in token) return <span>{token.p}</span>
  const s = status?.s
  const bg =
    s === 'tracked'
      ? 'bg-[var(--reader-tracked-bg)]'
      : s === 'known' || s === 'ignored'
        ? ''
        : 'bg-[var(--reader-new-bg)]'
  return (
    <span
      data-ordinal={token.i}
      role="button"
      tabIndex={-1}
      className={`cursor-pointer rounded-sm px-px hover:brightness-95 ${bg}`}
      onClick={() => onWordClick?.(token)}
    >
      {token.t}
    </span>
  )
})
```

- `PageView`: renders current `PageSlice` grouped by `paragraphIndex` (`<p>` per paragraph, sentences joined; insert `' '` between sentences of a paragraph), max-w-[720px] centered; Prev/Next buttons (Prev = pure navigation; Next = bulk-known for the current page range → advance → toast, wired fully in Task 11 — in THIS task Next just advances and exposes an `onNextPage(page)` callback prop).
- `WordCardPlaceholder`: fixed right panel (desktop ≥md) / bottom sheet (fixed bottom, <md) showing surface text, normalized text, current status badge and «Карточка слова появится в FLQ-5»; closes on Esc/backdrop. Selected word lives in `ReaderPage` state.
- Test: TokenSpan renders blue for statusless word, yellow for tracked, plain for known/ignored, plain span for ws/punct; click fires with token.

- [ ] Steps: failing test → implement → green → gates → commit `feat(FLQ-4.9): render highlighted page view with card placeholder`.

---

### Task 10: SentenceView + «Показать перевод» + vocab mini-list

**Files:**
- Create: `frontend/src/features/reader/SentenceView.tsx`
- Modify: `frontend/src/features/reader/ReaderPage.tsx`, `frontend/src/features/reader/useReaderQueries.ts` (add `useSegmentTranslation` lazy query)
- Test: `frontend/src/features/reader/SentenceView.test.tsx`

**Content:**
- One sentence centered (flat sentence list from paragraphs; index in store), large type; ‹/› side buttons.
- «Показать перевод ▾» button: on first expand fires `readerApi.segmentTranslation(lessonId, seg_id, uiTargetLang)` (target = user's translation language — reuse how onboarding stored it; take from `me` endpoint via existing `meApi` if available, else prop-drill the route's `lang`-independent setting; pin: use `target = 'ru'` fallback constant `DEFAULT_TRANSLATION_LANG` if me-profile lacks it, with a TODO(FLQ-9)). Rendered collapsed by default per mockup; shows text + badge «AI» (ADR-0003 labeling) when `source === 'ai'`; error states: 503 → «AI отключён администратором», 502 → «Не удалось перевести» + retry.
- Vocab mini-list: sentence's word tokens whose status is `tracked` → mini-cards (confidence circle + surface text; translation column left "—" until FLQ-5/6). Absent when none.
- Test: translation button fetches lazily exactly once and toggles; 503 shows disabled-message; tracked words of the sentence appear in the list.

- [ ] Steps: failing test → implement → green → gates → commit `feat(FLQ-4.10): add sentence view with on-demand translation`.

---

### Task 11: Bulk-known flow, undo toast, hotkeys, position sync, swipe

**Files:**
- Create: `frontend/src/features/reader/UndoToast.tsx`, `frontend/src/features/reader/useReaderHotkeys.ts`, `frontend/src/features/reader/usePositionSync.ts`, `frontend/src/features/reader/useSwipe.ts`
- Modify: `frontend/src/features/reader/ReaderPage.tsx`, `PageView.tsx`
- Test: `frontend/src/features/reader/bulkFlow.test.tsx`

**Content:**
- Next page: `bulkKnown({lesson_id, from_ordinal: page.fromOrdinal, to_ordinal: page.toOrdinal})` → on success: advance page, invalidate statuses, `setLastBulkActionId(action_id)`, show `UndoToast` («N слов помечены как known» + Отменить, auto-hide 6s; if `created_count === 0` — no toast, just advance).
- `UndoToast`: fixed bottom-center; Отменить → `undoBulk(actionId)` → invalidate statuses, clear id, hide.
- `useReaderHotkeys`: `keydown` on window — `ArrowLeft/ArrowRight` prev/next (page or sentence per mode), `m` toggle mode, `Escape` close card else navigate to library, `Ctrl+Z`/`Cmd+Z` undo if `lastBulkActionId`, `f` open font popover (toggle state), `s` toggle sidebar (page mode). Ignore events when target is input/textarea.
- `usePositionSync`: debounce 2s; on page/sentence/mode change PUT `{lesson_id, view_mode, current_segment_id: firstSentenceOfView.seg_id, current_token_ordinal: page.fromOrdinal|sentenceFirstWord.i}`; also flush on unmount.
- `useSwipe`: touchstart/touchend deltaX threshold 60px → prev/next; attach to the text container.
- Test (`bulkFlow.test.tsx`, mocked api): clicking Next calls bulkKnown with the page's ordinal range → toast appears with count → click Отменить calls undo and refetches statuses; `Ctrl+Z` triggers undo too; `m` toggles mode.

- [ ] Steps: failing test → implement → green → ALL frontend gates → commit `feat(FLQ-4.11): wire bulk-known undo, hotkeys, position sync and swipe`.

---

### Task 12: Finalization

- [ ] **Step 1: Full gate run, both stacks** (backend: ruff/format/pyright/pytest; frontend: tsc/eslint/vitest run/build).
- [ ] **Step 2: Reconcile spec** (status header → implemented; note any drift) + commit `docs(FLQ-4): reconcile design spec with implementation` scoped to the spec file.
- [ ] **Step 3: Backlog** — check FLQ-4 AC #1–#6 (AC#3 satisfied by WordCardPlaceholder), status Done, final summary (task_edit).
- [ ] **Step 4: PR + squash-merge** — PR `feat(FLQ-4): Reader page`, wait CI (BOTH backend and frontend workflows trigger — first PR to touch both paths), squash with manual message `feat(FLQ-4): add reader page with token highlighting and bulk-known`, body = why, no trailers; delete branch after merge.

---

## Self-Review (done at plan-writing time)

- **Spec coverage:** API-1..6 → Tasks 2,3,4,5,6; data model → Task 1; frontend architecture map → Tasks 7–11 file-for-file; hotkeys/AC#5 → Task 11; states §12 → Task 8; ADR-0005 highlight → Task 9; «Показать перевод» → Tasks 6+10; mobile (swipe, bottom sheet) → Tasks 9+11; gzip → Task 2. Deferred items in spec Non-Goals are absent from tasks — checked. No gaps found.
- **Type consistency:** wire keys `t/n/i/ws/p` identical in backend schemas (Task 2) and `api/reader.ts` (Task 7); `PageSlice.fromOrdinal/toOrdinal` feed `bulk-known` request fields (Task 11 ↔ Task 5); `ReaderPosition` fields match PUT body and `LessonDetail.reader_position`; exceptions of Task 6 map to the same details as FLQ-3's endpoint.
- **Known risks for the implementer, stated:** Task 2 depends on FLQ-1 storing paragraph+sentence segments with offsets — the reconstruction test will catch any mismatch immediately; Task 6 refactors FLQ-3's service (existing tests must stay green unchanged — treat them as the contract); frontend has NO prior tests — Task 7's vitest run is the first, so `tests/setup.ts` wiring issues surface there, fix within that task; the exact `word_count` in Task 2's fixture must be pinned after the first GREEN run, not guessed.
- **Placeholder scan:** Tasks 3–6 and 8–11 use compressed test descriptions with exact assertions enumerated (bulleted) rather than full listings — acceptable density for this plan's size, every assertion is concrete and every production interface/code is complete. No TBD/TODO left except the explicitly-marked `TODO(FLQ-9)` product decision in Task 10 (translation target language default), which is deliberate and documented.
