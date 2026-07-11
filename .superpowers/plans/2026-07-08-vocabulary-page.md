# FLQ-6 — Vocabulary Page (Increment 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Personal vocabulary page `/learn/$lang/vocabulary`: paginated table of token items with search, filters, bulk actions and an inline confidence picker shared with WordCard.

**Architecture:** Backend first: `list_items` + `bulk_action` in the vocabulary service, then `GET /api/vocabulary` + `POST /api/vocabulary/bulk` routes. Frontend: shared `ConfidencePicker` extracted from WordCard, then page skeleton (route/store/api), table, toolbar (search+filters), selection+bulk, and finally WordCard integration + states + mobile.

**Tech Stack:** FastAPI + SQLAlchemy 2 async; React 19 + TS strict + TanStack Router/Query + Zustand 5; pytest + testcontainers; Vitest + @testing-library.

**Spec:** `.superpowers/specs/2026-07-08-vocabulary-page-design.md` — binding (§ refs below).

## Global Constraints

- `flinq.core.textnorm.normalize_token` FROZEN; `token_items.token_text` is stored normalized and is the join key to `lesson_token_occurrences.normalized_text` and `dictionary_entries.headword_normalized`.
- Commits: conventional, English imperative ≤72 chars, body says why, NO Co-Authored-By, scoped `git commit -m "..." -- <paths>` (git add new files first — pathspec commit does not stage untracked files).
- Before every backend commit: `uv run ruff format <changed files>`, `uv run ruff check .`, `uv run pyright` (0 errors; 21 pre-existing warnings OK). CI also runs `ruff format --check`.
- Backend tests: `uv run pytest` (Docker/testcontainers). No per-test rollback — file-local autouse cleanup fixtures.
- Frontend: `corepack pnpm test` and `corepack pnpm lint` green per task.
- UNICODE: Cyrillic literals byte-for-byte; «1–4» uses EN DASH U+2013; «✓» is U+2713.
- Working dirs: backend commands from `backend/`, frontend from `frontend/`.
- API error contract: unauthenticated 401; >500 bulk ids → 422; foreign/unknown ids in bulk are silently skipped (`affected` counts real changes' targets found).

---

### Task 1: Backend service — `list_items`

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/service.py`
- Test: `backend/tests/modules/test_vocabulary_list.py` (new file)

**Interfaces:**
- Consumes: models `TokenItem`, `PersonalTranslation`, `ItemTag` (vocabulary), `Lesson`, `LessonSegment`, `LessonTokenOccurrence` (lesson_library), `DictionaryEntry`, `DictionarySourceVersion` (dictionary).
- Produces (Task 3 relies on these exact shapes):

```python
@dataclass
class VocabListItem:
    item_id: uuid.UUID
    kind: str                      # always "token" in this increment
    text: str
    status: str
    confidence: int | None
    primary_translation_text: str | None
    primary_translation_target: str | None
    tags: list[str]
    pos: str | None
    context: str | None
    created_at: datetime

async def list_items(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    language_code: str,
    target_language_code: str,
    kind: str,                     # "token" | "all" — both mean token-only for now
    statuses: list[str],           # subset of tracked/known/ignored, non-empty
    confidence_min: int | None,
    confidence_max: int | None,
    tags: list[str],
    q: str | None,
    added_after: datetime | None,
    sort: str,                     # "created_at" | "text"
    sort_dir: str,                 # "asc" | "desc"
    page: int,
    page_size: int,
) -> tuple[list[VocabListItem], int]:   # (page items, total)
```

- [ ] **Step 1: Write failing tests**

Create `backend/tests/modules/test_vocabulary_list.py`:

```python
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.dictionary.models import DictionaryEntry, DictionarySourceVersion
from flinq.modules.identity.repo import UserRepo
from flinq.modules.lesson_library.models import Lesson, LessonSegment, LessonTokenOccurrence
from flinq.modules.vocabulary import service
from flinq.modules.vocabulary.models import ItemTag, PersonalNote, PersonalTranslation, TokenItem


async def _make_user(s: AsyncSession) -> uuid.UUID:
    user = await UserRepo(s).create(
        email=f"{uuid.uuid4().hex}@t.io",
        password_hash=hash_password("x"),
        display_name="T",
        role="learner",
    )
    await s.flush()
    return user.id


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    async with session_scope() as s:
        for model in (
            PersonalTranslation,
            PersonalNote,
            ItemTag,
            TokenItem,
            Lesson,  # cascades sources/segments/occurrences via DB FKs
            DictionaryEntry,
            DictionarySourceVersion,
        ):
            await s.execute(delete(model))


async def _item(
    s: AsyncSession,
    user_id: uuid.UUID,
    text: str,
    *,
    lang: str = "pt",
    status: str = "tracked",
    confidence: int | None = 1,
) -> TokenItem:
    item = TokenItem(
        user_id=user_id,
        language_code=lang,
        token_text=text,
        status=status,
        confidence=confidence,
    )
    s.add(item)
    await s.flush()
    return item


def _defaults() -> dict:
    return {
        "target_language_code": "ru",
        "kind": "all",
        "statuses": ["tracked", "known", "ignored"],
        "confidence_min": None,
        "confidence_max": None,
        "tags": [],
        "q": None,
        "added_after": None,
        "sort": "created_at",
        "sort_dir": "desc",
        "page": 1,
        "page_size": 25,
    }


async def test_list_scopes_by_owner_and_language():
    async with session_scope() as s:
        me = await _make_user(s)
        other = await _make_user(s)
        await _item(s, me, "cada", lang="pt")
        await _item(s, me, "casa", lang="en")     # other language
        await _item(s, other, "porta", lang="pt")  # other user
    async with session_scope() as s:
        items, total = await service.list_items(
            s, user_id=me, language_code="pt", **_defaults()
        )
    assert total == 1
    assert [i.text for i in items] == ["cada"]


async def test_list_filters_status_and_confidence():
    async with session_scope() as s:
        user_id = await _make_user(s)
        await _item(s, user_id, "um", status="tracked", confidence=1)
        await _item(s, user_id, "dois", status="tracked", confidence=3)
        await _item(s, user_id, "tres", status="known", confidence=None)
        await _item(s, user_id, "quatro", status="ignored", confidence=None)
    kw = _defaults()
    kw["statuses"] = ["tracked", "known"]
    kw["confidence_min"] = 2
    kw["confidence_max"] = 4
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    # confidence narrows only tracked rows; known passes regardless (spec §3.1)
    assert total == 2
    assert sorted(i.text for i in items) == ["dois", "tres"]


async def test_list_search_matches_term_and_primary_translation():
    async with session_scope() as s:
        user_id = await _make_user(s)
        a = await _item(s, user_id, "cada")
        await _item(s, user_id, "porta")
        s.add(
            PersonalTranslation(
                owner_user_id=user_id,
                item_kind="token",
                item_id=a.id,
                target_language_code="ru",
                translation_text="каждый",
                is_primary=True,
                source_type="user",
            )
        )
        await s.flush()
    kw = _defaults()
    kw["q"] = "кажд"
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 1 and items[0].text == "cada"
    assert items[0].primary_translation_text == "каждый"
    kw["q"] = "port"
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 1 and items[0].text == "porta"


async def test_list_filters_tags_with_and_semantics():
    async with session_scope() as s:
        user_id = await _make_user(s)
        a = await _item(s, user_id, "cada")
        b = await _item(s, user_id, "porta")
        for item, tag in ((a, "verbs"), (a, "b1"), (b, "verbs")):
            s.add(
                ItemTag(
                    owner_user_id=user_id, item_kind="token", item_id=item.id, tag_name=tag
                )
            )
        await s.flush()
    kw = _defaults()
    kw["tags"] = ["verbs", "b1"]
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 1 and items[0].text == "cada"
    assert sorted(items[0].tags) == ["b1", "verbs"]


async def test_list_sort_and_pagination():
    async with session_scope() as s:
        user_id = await _make_user(s)
        for t in ("aaa", "bbb", "ccc"):
            await _item(s, user_id, t)
    kw = _defaults()
    kw["sort"] = "text"
    kw["sort_dir"] = "asc"
    kw["page_size"] = 25
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 3
    assert [i.text for i in items] == ["aaa", "bbb", "ccc"]
    kw["page"] = 2
    kw["page_size"] = 25
    async with session_scope() as s:
        items, _ = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert items == []


async def test_list_added_after():
    async with session_scope() as s:
        user_id = await _make_user(s)
        await _item(s, user_id, "cada")
    cutoff = datetime.now(timezone.utc) + timedelta(days=1)
    kw = _defaults()
    kw["added_after"] = cutoff
    async with session_scope() as s:
        _, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 0


async def test_list_enriches_context_and_pos():
    async with session_scope() as s:
        user_id = await _make_user(s)
        await _item(s, user_id, "cada")
        lesson = Lesson(
            owner_user_id=user_id,
            language_code="pt",
            title="L",
            raw_text="Cada casa.",
            status="ready",
        )
        s.add(lesson)
        await s.flush()
        seg = LessonSegment(
            lesson_id=lesson.id,
            ordinal=0,
            segment_type="sentence",
            text="Cada casa tem uma porta.",
            start_char_offset=0,
            end_char_offset=24,
        )
        s.add(seg)
        await s.flush()
        s.add(
            LessonTokenOccurrence(
                lesson_id=lesson.id,
                segment_id=seg.id,
                ordinal_in_lesson=0,
                ordinal_in_segment=0,
                surface_text="Cada",
                normalized_text="cada",
                start_char_offset=0,
                end_char_offset=4,
                is_word_like=True,
            )
        )
        version = DictionarySourceVersion(
            source_name="kaikki",
            source_language_code="pt",
            target_language_code="ru",
            source_version="v1",
            status="active",
        )
        s.add(version)
        await s.flush()
        s.add(
            DictionaryEntry(
                source_version_id=version.id,
                source_language_code="pt",
                headword="cada",
                headword_normalized="cada",
                part_of_speech="det",
                entry_key="cada:det",
            )
        )
        await s.flush()
    async with session_scope() as s:
        items, _ = await service.list_items(
            s, user_id=user_id, language_code="pt", **_defaults()
        )
    assert items[0].context == "Cada casa tem uma porta."
    assert items[0].pos == "det"


async def test_list_nulls_when_no_enrichment():
    async with session_scope() as s:
        user_id = await _make_user(s)
        await _item(s, user_id, "cada")
    async with session_scope() as s:
        items, _ = await service.list_items(
            s, user_id=user_id, language_code="pt", **_defaults()
        )
    it = items[0]
    assert it.primary_translation_text is None
    assert it.context is None and it.pos is None and it.tags == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/modules/test_vocabulary_list.py -q`
Expected: FAIL — `service.list_items` does not exist.

- [ ] **Step 3: Implement `list_items` in service.py**

Add imports at the top of `service.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, delete, exists, func, or_, select, update

from flinq.modules.dictionary.models import DictionaryEntry, DictionarySourceVersion
from flinq.modules.lesson_library.models import Lesson, LessonSegment, LessonTokenOccurrence
```

(`dataclass, field` and `delete/select/update` are already imported — merge, don't duplicate.)

Add after `LookupResult`:

```python
@dataclass
class VocabListItem:
    item_id: uuid.UUID
    kind: str
    text: str
    status: str
    confidence: int | None
    primary_translation_text: str | None
    primary_translation_target: str | None
    tags: list[str] = field(default_factory=list)
    pos: str | None = None
    context: str | None = None
    created_at: datetime | None = None
```

Add at the end of the module:

```python
async def list_items(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    language_code: str,
    target_language_code: str,
    kind: str,
    statuses: list[str],
    confidence_min: int | None,
    confidence_max: int | None,
    tags: list[str],
    q: str | None,
    added_after: datetime | None,
    sort: str,
    sort_dir: str,
    page: int,
    page_size: int,
) -> tuple[list[VocabListItem], int]:
    """Paginated vocabulary list (spec §3.1). `kind` accepted for the URL
    contract but both values mean token-only until phrase_items exist."""
    del kind  # token-only increment
    conditions = [
        TokenItem.user_id == user_id,
        TokenItem.language_code == language_code,
        TokenItem.status.in_(statuses),
    ]
    if confidence_min is not None or confidence_max is not None:
        conf = []
        if confidence_min is not None:
            conf.append(TokenItem.confidence >= confidence_min)
        if confidence_max is not None:
            conf.append(TokenItem.confidence <= confidence_max)
        # narrows only tracked rows; known/ignored pass (spec §3.1)
        conditions.append(or_(TokenItem.status != "tracked", and_(*conf)))
    for tag in tags:
        conditions.append(
            exists().where(
                ItemTag.owner_user_id == user_id,
                ItemTag.item_kind == "token",
                ItemTag.item_id == TokenItem.id,
                ItemTag.tag_name == tag,
            )
        )
    if q:
        pattern = f"%{q}%"
        conditions.append(
            or_(
                TokenItem.token_text.ilike(pattern),
                exists().where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == "token",
                    PersonalTranslation.item_id == TokenItem.id,
                    PersonalTranslation.target_language_code == target_language_code,
                    PersonalTranslation.is_primary.is_(True),
                    PersonalTranslation.translation_text.ilike(pattern),
                ),
            )
        )
    if added_after is not None:
        conditions.append(TokenItem.created_at >= added_after)

    total = (
        await session.execute(select(func.count()).select_from(TokenItem).where(*conditions))
    ).scalar_one()

    order_col = TokenItem.token_text if sort == "text" else TokenItem.created_at
    order_by = order_col.asc() if sort_dir == "asc" else order_col.desc()
    rows = (
        (
            await session.execute(
                select(TokenItem)
                .where(*conditions)
                .order_by(order_by, TokenItem.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return [], total

    ids = [r.id for r in rows]
    texts = [r.token_text for r in rows]

    primary_map: dict[uuid.UUID, PersonalTranslation] = {
        t.item_id: t
        for t in (
            await session.execute(
                select(PersonalTranslation).where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == "token",
                    PersonalTranslation.item_id.in_(ids),
                    PersonalTranslation.target_language_code == target_language_code,
                    PersonalTranslation.is_primary.is_(True),
                )
            )
        )
        .scalars()
        .all()
    }

    tags_map: dict[uuid.UUID, list[str]] = {}
    for item_id, tag_name in (
        await session.execute(
            select(ItemTag.item_id, ItemTag.tag_name)
            .where(
                ItemTag.owner_user_id == user_id,
                ItemTag.item_kind == "token",
                ItemTag.item_id.in_(ids),
            )
            .order_by(ItemTag.tag_name)
        )
    ).all():
        tags_map.setdefault(item_id, []).append(tag_name)

    pos_map: dict[str, str] = {
        headword: pos
        for headword, pos in (
            await session.execute(
                select(DictionaryEntry.headword_normalized, DictionaryEntry.part_of_speech)
                .distinct(DictionaryEntry.headword_normalized)
                .join(
                    DictionarySourceVersion,
                    DictionaryEntry.source_version_id == DictionarySourceVersion.id,
                )
                .where(
                    DictionarySourceVersion.status == "active",
                    DictionaryEntry.source_language_code == language_code,
                    DictionaryEntry.headword_normalized.in_(texts),
                    DictionaryEntry.part_of_speech.is_not(None),
                )
                .order_by(DictionaryEntry.headword_normalized, DictionaryEntry.entry_key)
            )
        ).all()
        if pos is not None
    }

    # One example sentence per token: latest lesson's occurrence (spec §3.1).
    occ = (
        select(
            LessonTokenOccurrence.normalized_text.label("norm"),
            LessonSegment.text.label("segment_text"),
        )
        .distinct(LessonTokenOccurrence.normalized_text)
        .join(Lesson, LessonTokenOccurrence.lesson_id == Lesson.id)
        .join(LessonSegment, LessonTokenOccurrence.segment_id == LessonSegment.id)
        .where(
            Lesson.owner_user_id == user_id,
            Lesson.language_code == language_code,
            LessonTokenOccurrence.normalized_text.in_(texts),
        )
        .order_by(
            LessonTokenOccurrence.normalized_text,
            Lesson.created_at.desc(),
            LessonTokenOccurrence.ordinal_in_lesson,
        )
    )
    context_map: dict[str, str] = {
        norm: segment_text for norm, segment_text in (await session.execute(occ)).all()
    }

    result = []
    for r in rows:
        primary = primary_map.get(r.id)
        result.append(
            VocabListItem(
                item_id=r.id,
                kind="token",
                text=r.token_text,
                status=r.status,
                confidence=r.confidence,
                primary_translation_text=primary.translation_text if primary else None,
                primary_translation_target=(
                    primary.target_language_code if primary else None
                ),
                tags=tags_map.get(r.id, []),
                pos=pos_map.get(r.token_text),
                context=context_map.get(r.token_text),
                created_at=r.created_at,
            )
        )
    return result, total
```

Note: `exists().where(...)` with multiple args and `select(...).distinct(col)` (PostgreSQL `DISTINCT ON`) are the SQLAlchemy 2 idioms; keep them exactly.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/modules/test_vocabulary_list.py tests/modules/test_vocabulary_service.py -q`
Expected: PASS (new file 8 tests + existing suite untouched).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format src/flinq/modules/vocabulary/service.py tests/modules/test_vocabulary_list.py
uv run ruff check . && uv run pyright
git add tests/modules/test_vocabulary_list.py
git commit -m "feat(FLQ-6): vocabulary list service with filters and enrichment" -- src/flinq/modules/vocabulary/service.py tests/modules/test_vocabulary_list.py
```

---

### Task 2: Backend service — `bulk_action`

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/service.py`
- Test: `backend/tests/modules/test_vocabulary_bulk.py` (new file)

**Interfaces:**
- Produces (Task 3 relies on):

```python
async def bulk_action(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    action: str,          # "set_known" | "set_ignored" | "delete" | "add_tag"
    tag_name: str | None,
) -> int:                 # affected = count of caller-owned items found
```

Semantics (spec §3.2): foreign/unknown ids silently skipped; `set_known`/`set_ignored` → status + `confidence=NULL`; `delete` → hard-delete items plus their `personal_translations`/`personal_notes`/`item_tags` rows (explicit — no FK cascade on the polymorphic link); `add_tag` → `on_conflict_do_nothing` per item; one transaction (single commit at the end).

- [ ] **Step 1: Write failing tests**

Create `backend/tests/modules/test_vocabulary_bulk.py` (reuse `_make_user`, `_clean` for vocabulary models only, and an `_item` helper as in Task 1's test file — copy them; file-local fixtures are the repo convention):

```python
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo
from flinq.modules.vocabulary import service
from flinq.modules.vocabulary.models import ItemTag, PersonalNote, PersonalTranslation, TokenItem


async def _make_user(s: AsyncSession) -> uuid.UUID:
    user = await UserRepo(s).create(
        email=f"{uuid.uuid4().hex}@t.io",
        password_hash=hash_password("x"),
        display_name="T",
        role="learner",
    )
    await s.flush()
    return user.id


async def _item(s: AsyncSession, user_id: uuid.UUID, text: str) -> TokenItem:
    item = TokenItem(
        user_id=user_id, language_code="pt", token_text=text, status="tracked", confidence=1
    )
    s.add(item)
    await s.flush()
    return item


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    async with session_scope() as s:
        for model in (PersonalTranslation, PersonalNote, ItemTag, TokenItem):
            await s.execute(delete(model))


async def test_bulk_set_known_and_skips_foreign():
    async with session_scope() as s:
        me = await _make_user(s)
        other = await _make_user(s)
        mine = await _item(s, me, "cada")
        foreign = await _item(s, other, "porta")
        mine_id, foreign_id = mine.id, foreign.id
    async with session_scope() as s:
        affected = await service.bulk_action(
            s,
            user_id=me,
            item_ids=[mine_id, foreign_id, uuid.uuid4()],
            action="set_known",
            tag_name=None,
        )
    assert affected == 1
    async with session_scope() as s:
        mine_db = await s.get(TokenItem, mine_id)
        foreign_db = await s.get(TokenItem, foreign_id)
        assert mine_db is not None and mine_db.status == "known"
        assert mine_db.confidence is None
        assert foreign_db is not None and foreign_db.status == "tracked"


async def test_bulk_delete_cascades_annotations():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = await _item(s, user_id, "cada")
        item_id = item.id
        s.add(
            PersonalTranslation(
                owner_user_id=user_id,
                item_kind="token",
                item_id=item_id,
                target_language_code="ru",
                translation_text="каждый",
                is_primary=True,
                source_type="user",
            )
        )
        s.add(
            PersonalNote(
                owner_user_id=user_id, item_kind="token", item_id=item_id, note_text="n"
            )
        )
        s.add(
            ItemTag(
                owner_user_id=user_id, item_kind="token", item_id=item_id, tag_name="verbs"
            )
        )
        await s.flush()
    async with session_scope() as s:
        affected = await service.bulk_action(
            s, user_id=user_id, item_ids=[item_id], action="delete", tag_name=None
        )
    assert affected == 1
    async with session_scope() as s:
        assert await s.get(TokenItem, item_id) is None
        for model in (PersonalTranslation, PersonalNote, ItemTag):
            left = (await s.execute(select(model))).scalars().all()
            assert left == []


async def test_bulk_add_tag_idempotent():
    async with session_scope() as s:
        user_id = await _make_user(s)
        a = await _item(s, user_id, "cada")
        b = await _item(s, user_id, "porta")
        s.add(
            ItemTag(owner_user_id=user_id, item_kind="token", item_id=a.id, tag_name="b1")
        )
        await s.flush()
        a_id, b_id = a.id, b.id
    async with session_scope() as s:
        affected = await service.bulk_action(
            s, user_id=user_id, item_ids=[a_id, b_id], action="add_tag", tag_name="b1"
        )
    assert affected == 2
    async with session_scope() as s:
        rows = (await s.execute(select(ItemTag.item_id, ItemTag.tag_name))).all()
    assert sorted(str(r[0]) for r in rows) == sorted([str(a_id), str(b_id)])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/modules/test_vocabulary_bulk.py -q`
Expected: FAIL — `bulk_action` missing.

- [ ] **Step 3: Implement**

Append to `service.py`:

```python
async def bulk_action(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    action: str,
    tag_name: str | None,
) -> int:
    """Bulk operation over the caller's token items (spec §3.2).

    Unknown/foreign ids are silently skipped. One transaction.
    """
    owned = (
        (
            await session.execute(
                select(TokenItem.id).where(
                    TokenItem.user_id == user_id, TokenItem.id.in_(item_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    if not owned:
        return 0

    if action in ("set_known", "set_ignored"):
        status = "known" if action == "set_known" else "ignored"
        await session.execute(
            update(TokenItem)
            .where(TokenItem.id.in_(owned))
            .values(status=status, confidence=None)
        )
    elif action == "delete":
        for model in (PersonalTranslation, PersonalNote, ItemTag):
            await session.execute(
                delete(model).where(
                    model.owner_user_id == user_id,
                    model.item_kind == "token",
                    model.item_id.in_(owned),
                )
            )
        await session.execute(delete(TokenItem).where(TokenItem.id.in_(owned)))
    elif action == "add_tag":
        assert tag_name is not None  # validated at the API layer
        for item_id in owned:
            await session.execute(
                pg_insert(ItemTag)
                .values(
                    id=uuid.uuid4(),
                    owner_user_id=user_id,
                    item_kind="token",
                    item_id=item_id,
                    tag_name=tag_name,
                )
                .on_conflict_do_nothing(constraint="uq_item_tags")
            )
    await session.commit()
    return len(owned)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/modules/test_vocabulary_bulk.py tests/modules/ -q`
Expected: PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format src/flinq/modules/vocabulary/service.py tests/modules/test_vocabulary_bulk.py
uv run ruff check . && uv run pyright
git add tests/modules/test_vocabulary_bulk.py
git commit -m "feat(FLQ-6): vocabulary bulk action service" -- src/flinq/modules/vocabulary/service.py tests/modules/test_vocabulary_bulk.py
```

---

### Task 3: API — `GET /api/vocabulary` + `POST /api/vocabulary/bulk`

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/schemas.py`
- Modify: `backend/src/flinq/api/vocabulary.py`
- Test: `backend/tests/api/test_vocabulary_page.py` (new file)

**Interfaces:**
- Consumes: Task 1/2 service functions.
- Produces (frontend Task 5 relies on):
  - `GET /api/vocabulary?lang=&target=&kind=&status=&confidence_min=&confidence_max=&tag=&q=&added_after=&sort=&sort_dir=&page=&page_size=` → `{items: [...], total, page, page_size}` with item JSON exactly per spec §3.1 (`primary_translation` nested object or null).
  - `POST /api/vocabulary/bulk` body `{item_ids: [uuid...] (1..500), action, tag_name?}` → `{affected: N}`; 422 when >500 ids or `add_tag` without tag_name.

- [ ] **Step 1: Schemas**

Append to `schemas.py`:

```python
class PrimaryTranslationOut(BaseModel):
    text: str
    target_language_code: str


class VocabListItemOut(BaseModel):
    item_id: uuid.UUID
    kind: Literal["token"]
    text: str
    status: Literal["tracked", "known", "ignored"]
    confidence: int | None
    primary_translation: PrimaryTranslationOut | None
    tags: list[str]
    pos: str | None
    context: str | None
    created_at: datetime


class VocabListResponse(BaseModel):
    items: list[VocabListItemOut]
    total: int
    page: int
    page_size: int


class BulkActionRequest(BaseModel):
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: Literal["set_known", "set_ignored", "delete", "add_tag"]
    tag_name: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def _tag_required_for_add_tag(self) -> BulkActionRequest:
        if self.action == "add_tag" and self.tag_name is None:
            raise ValueError("tag_name required for add_tag")
        return self


class BulkActionResponse(BaseModel):
    affected: int
```

(add `from datetime import datetime` to the file's imports).

- [ ] **Step 2: Write failing API tests**

Create `backend/tests/api/test_vocabulary_page.py` (same `_client`/`_register`/`_clean` pattern as `tests/api/test_vocabulary.py` — copy those helpers into this file):

```python
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from flinq.core.db import session_scope
from flinq.main import create_app
from flinq.modules.vocabulary.models import ItemTag, PersonalNote, PersonalTranslation, TokenItem


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    async with session_scope() as s:
        for model in (PersonalTranslation, PersonalNote, ItemTag, TokenItem):
            await s.execute(delete(model))


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def _register(c: AsyncClient) -> str:
    r = await c.post(
        "/auth/register",
        json={
            "display_name": "T",
            "email": f"{uuid.uuid4().hex}@t.io",
            "password": "abcdefghij",
        },
    )
    assert r.status_code == 201
    csrf = c.cookies.get("flinq_csrf")
    assert csrf
    return csrf


async def _create_item(c: AsyncClient, h: dict[str, str], text: str) -> str:
    r = await c.post(
        "/api/vocabulary/items",
        headers=h,
        json={
            "kind": "token",
            "language_code": "pt",
            "text": text,
            "status": "tracked",
            "confidence": 1,
        },
    )
    assert r.status_code == 201
    return r.json()["item_id"]


async def test_list_returns_items_with_defaults():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        await _create_item(c, h, "cada")
        await _create_item(c, h, "porta")
        r = await c.get("/api/vocabulary", params={"lang": "pt"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2 and body["page"] == 1 and body["page_size"] == 25
        # created_at desc default: porta created last comes first
        assert [i["text"] for i in body["items"]] == ["porta", "cada"]
        assert body["items"][0]["primary_translation"] is None


async def test_list_filters_and_search_params():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        await _create_item(c, h, "cada")
        r = await c.get(
            "/api/vocabulary",
            params={"lang": "pt", "status": ["known"], "q": "cada"},
        )
        assert r.status_code == 200 and r.json()["total"] == 0
        r = await c.get(
            "/api/vocabulary",
            params={"lang": "pt", "status": ["tracked"], "q": "cad"},
        )
        assert r.json()["total"] == 1


async def test_list_requires_auth():
    async with await _client() as c:
        r = await c.get("/api/vocabulary", params={"lang": "pt"})
        assert r.status_code == 401


async def test_bulk_set_known_and_delete():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        a = await _create_item(c, h, "cada")
        b = await _create_item(c, h, "porta")
        r = await c.post(
            "/api/vocabulary/bulk",
            headers=h,
            json={"item_ids": [a, b], "action": "set_known"},
        )
        assert r.status_code == 200 and r.json()["affected"] == 2
        r = await c.post(
            "/api/vocabulary/bulk",
            headers=h,
            json={"item_ids": [a], "action": "delete"},
        )
        assert r.status_code == 200 and r.json()["affected"] == 1
        r = await c.get("/api/vocabulary", params={"lang": "pt"})
        assert r.json()["total"] == 1


async def test_bulk_validation_422():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        r = await c.post(
            "/api/vocabulary/bulk",
            headers=h,
            json={"item_ids": [str(uuid.uuid4())] * 501, "action": "set_known"},
        )
        assert r.status_code == 422
        r = await c.post(
            "/api/vocabulary/bulk",
            headers=h,
            json={"item_ids": [str(uuid.uuid4())], "action": "add_tag"},
        )
        assert r.status_code == 422
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/api/test_vocabulary_page.py -q`
Expected: FAIL — 404/405 (routes missing).

- [ ] **Step 4: Routes**

In `api/vocabulary.py` add imports (`datetime`, new schemas, `Body` not needed) and two routes:

```python
@router.get("", response_model=VocabListResponse)
async def list_vocabulary(
    request: Request,
    lang: LangCode,
    session: Annotated[AsyncSession, Depends(get_session)],
    target: LangCode = "ru",
    kind: Literal["token", "all"] = "all",
    status_filter: Annotated[
        list[Literal["tracked", "known", "ignored"]] | None, Query(alias="status")
    ] = None,
    confidence_min: Annotated[int | None, Query(ge=0, le=5)] = None,
    confidence_max: Annotated[int | None, Query(ge=0, le=5)] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=128)] = None,
    added_after: datetime | None = None,
    sort: Literal["created_at", "text"] = "created_at",
    sort_dir: Literal["asc", "desc"] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Literal[25, 50, 100] = 25,
) -> VocabListResponse:
    user_id = _require_user(request)
    items, total = await service.list_items(
        session,
        user_id=user_id,
        language_code=lang,
        target_language_code=target,
        kind=kind,
        statuses=list(status_filter) if status_filter else ["tracked", "known", "ignored"],
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        tags=list(tag) if tag else [],
        q=q,
        added_after=added_after,
        sort=sort,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
    )
    return VocabListResponse(
        items=[
            VocabListItemOut(
                item_id=i.item_id,
                kind="token",
                text=i.text,
                status=cast('Literal["tracked", "known", "ignored"]', i.status),
                confidence=i.confidence,
                primary_translation=(
                    PrimaryTranslationOut(
                        text=i.primary_translation_text,
                        target_language_code=i.primary_translation_target or target,
                    )
                    if i.primary_translation_text is not None
                    else None
                ),
                tags=i.tags,
                pos=i.pos,
                context=i.context,
                created_at=i.created_at,
            )
            for i in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/bulk", response_model=BulkActionResponse)
async def bulk(
    request: Request,
    body: BulkActionRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BulkActionResponse:
    user_id = _require_user(request)
    affected = await service.bulk_action(
        session,
        user_id=user_id,
        item_ids=body.item_ids,
        action=body.action,
        tag_name=body.tag_name,
    )
    return BulkActionResponse(affected=affected)
```

Note: FastAPI route ordering — register `GET ""` and `POST "/bulk"` BEFORE the existing `/lookup` route is not required (paths don't collide), just append after existing routes. `VocabListItemOut.created_at` is non-optional — service always fills it for DB rows.

- [ ] **Step 5: Run the backend suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format src/flinq/api/vocabulary.py src/flinq/modules/vocabulary/schemas.py tests/api/test_vocabulary_page.py
uv run ruff check . && uv run pyright
git add tests/api/test_vocabulary_page.py
git commit -m "feat(FLQ-6): vocabulary list and bulk endpoints" -- src/flinq/api/vocabulary.py src/flinq/modules/vocabulary/schemas.py tests/api/test_vocabulary_page.py
```

---

### Task 4: Shared ConfidencePicker (extract from WordCard)

**Files:**
- Create: `frontend/src/components/ConfidencePicker.tsx`
- Modify: `frontend/src/features/reader/WordCard.tsx` (footer → picker component)
- Test: `frontend/src/components/ConfidencePicker.test.tsx` (new)

**Interfaces:**
- Produces (Task 6 relies on):

```tsx
interface ConfidencePickerProps {
  status: 'new' | 'tracked' | 'known' | 'ignored'
  confidence: number | null
  onSelect: (status: 'tracked' | 'known' | 'ignored', confidence: number | null) => void
  size?: 'md' | 'sm'   // md = WordCard footer (h-8 w-8), sm = table rows (h-6 w-6, text-xs)
}
export function ConfidencePicker(props: ConfidencePickerProps): JSX.Element
```

Renders `🗑 [1][2][3][4] ✓` exactly as the current WordCard footer (same aria-labels «Игнорировать», «Уровень N», «Изучено»; same active-state classes; `confidence === 0` → no pill highlighted). No border-t/mt-4 wrapper inside the component — layout stays at call sites.

- [ ] **Step 1: Write failing tests**

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ConfidencePicker } from './ConfidencePicker'

describe('ConfidencePicker', () => {
  it('fires tracked/N, known and ignored selections', () => {
    const onSelect = vi.fn()
    render(<ConfidencePicker status="tracked" confidence={2} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: 'Уровень 3' }))
    expect(onSelect).toHaveBeenCalledWith('tracked', 3)
    fireEvent.click(screen.getByRole('button', { name: 'Изучено' }))
    expect(onSelect).toHaveBeenCalledWith('known', null)
    fireEvent.click(screen.getByRole('button', { name: 'Игнорировать' }))
    expect(onSelect).toHaveBeenCalledWith('ignored', null)
  })

  it('highlights the active pill and none for confidence 0', () => {
    const { rerender } = render(
      <ConfidencePicker status="tracked" confidence={2} onSelect={() => {}} />,
    )
    expect(screen.getByRole('button', { name: 'Уровень 2' }).className).toContain('border-primary')
    rerender(<ConfidencePicker status="tracked" confidence={0} onSelect={() => {}} />)
    for (const n of [1, 2, 3, 4]) {
      expect(screen.getByRole('button', { name: `Уровень ${n}` }).className).not.toContain(
        'border-primary',
      )
    }
  })
})
```

- [ ] **Step 2: Run to verify failure**, then **Step 3: Implement**

Create `frontend/src/components/ConfidencePicker.tsx` by MOVING the JSX from WordCard.tsx lines "Footer: 🗑 [1][2][3][4] ✓" block (the `div` with the three buttons/pills) into the new component, parameterized:

```tsx
import { Check, Trash2 } from 'lucide-react'

const PILLS = [1, 2, 3, 4] as const

interface Props {
  status: 'new' | 'tracked' | 'known' | 'ignored'
  confidence: number | null
  onSelect: (status: 'tracked' | 'known' | 'ignored', confidence: number | null) => void
  size?: 'md' | 'sm'
}

/** Shared status/confidence widget: 🗑 [1][2][3][4] ✓ (ADR-0005 + FLQ-5 §2). */
export function ConfidencePicker({ status, confidence, onSelect, size = 'md' }: Props) {
  const pill = size === 'md' ? 'h-8 w-8 text-sm' : 'h-6 w-6 text-xs'
  const icon = size === 'md' ? 'h-4 w-4' : 'h-3.5 w-3.5'
  const iconBtn = size === 'md' ? 'p-2' : 'p-1.5'
  return (
    <div className="flex items-center justify-between gap-2">
      <button
        type="button" aria-label="Игнорировать" title="Игнорировать"
        onClick={() => onSelect('ignored', null)}
        className={`rounded-full border ${iconBtn} hover:bg-accent ${status === 'ignored' ? 'border-foreground' : 'border-border'}`}
      >
        <Trash2 className={icon} />
      </button>
      <div className="flex items-center gap-1">
        {PILLS.map((n) => (
          <button
            key={n} type="button" aria-label={`Уровень ${n}`} title={`Уверенность ${n}/4`}
            onClick={() => onSelect('tracked', n)}
            className={`flex ${pill} items-center justify-center rounded-full border ${
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
        onClick={() => onSelect('known', null)}
        className={`rounded-full border ${iconBtn} hover:bg-accent ${status === 'known' ? 'border-primary bg-primary/10' : 'border-border'}`}
      >
        <Check className={icon} />
      </button>
    </div>
  )
}
```

In WordCard.tsx replace the footer block's inner content with:

```tsx
        {data && (
          <div className="mt-4 border-t border-border pt-3">
            <ConfidencePicker
              status={status}
              confidence={confidence}
              onSelect={(s, c) => applyStatus(s, c)}
            />
          </div>
        )}
```

(import `ConfidencePicker` from `@/components/ConfidencePicker`; remove the now-unused `Check`, `Trash2` imports and the `PILLS` const from WordCard.)

- [ ] **Step 4: Run FULL frontend suite** — `corepack pnpm test` (WordCard tests must pass unchanged: identical roles/aria-labels/classes) and `corepack pnpm lint`.

- [ ] **Step 5: Commit**

```bash
git add src/components/ConfidencePicker.tsx src/components/ConfidencePicker.test.tsx
git commit -m "feat(FLQ-6): extract shared confidence picker from wordcard" -- src/components/ConfidencePicker.tsx src/components/ConfidencePicker.test.tsx src/features/reader/WordCard.tsx
```

---

### Task 5: Frontend API layer, store, route, nav link (page skeleton)

**Files:**
- Modify: `frontend/src/api/vocabulary.ts`
- Create: `frontend/src/features/vocabulary/vocabularyStore.ts`
- Create: `frontend/src/features/vocabulary/useVocabularyQuery.ts`
- Create: `frontend/src/features/vocabulary/VocabularyPage.tsx` (skeleton: header, tabs, count — table lands in Task 6)
- Create: `frontend/src/routes/learn.$lang.vocabulary.tsx`
- Modify: `frontend/src/routeTree.ts`, `frontend/src/components/AppTopBar.tsx`

**Interfaces:**
- Produces:

```ts
// api/vocabulary.ts additions
export interface VocabListItem {
  item_id: string; kind: 'token'; text: string
  status: 'tracked' | 'known' | 'ignored'; confidence: number | null
  primary_translation: { text: string; target_language_code: string } | null
  tags: string[]; pos: string | null; context: string | null; created_at: string
}
export interface VocabListResponse { items: VocabListItem[]; total: number; page: number; page_size: number }
export interface VocabListParams {
  lang: string; target?: string
  status?: ('tracked' | 'known' | 'ignored')[]
  confidence_min?: number; confidence_max?: number
  tag?: string[]; q?: string; added_after?: string
  sort?: 'created_at' | 'text'; sort_dir?: 'asc' | 'desc'
  page?: number; page_size?: number
}
vocabularyApi.list(params: VocabListParams): Promise<VocabListResponse>
vocabularyApi.bulk(body: { item_ids: string[]; action: 'set_known' | 'set_ignored' | 'delete' | 'add_tag'; tag_name?: string }): Promise<{ affected: number }>
```

```ts
// vocabularyStore.ts — Zustand, in-memory (NO persist)
export type VocabTab = 'all' | 'words' | 'phrases' | 'due'
interface VocabularyState {
  q: string
  statuses: ('tracked' | 'known' | 'ignored')[]     // default all three
  confidence: [number, number] | null               // null = off; range 1..4
  tags: string[]
  addedPreset: '7d' | '30d' | 'all'                 // default 'all'
  sort: 'created_at' | 'text'; sortDir: 'asc' | 'desc'
  page: number; pageSize: 25 | 50 | 100
  selection: string[]
  setQ / setStatuses / setConfidence / setTags / setAddedPreset / setSort / setPage / setPageSize
  toggleSelected(id) / selectMany(ids) / clearSelection()
  resetFilters()
}
```

Filter/`q`/tab changes reset `page → 1` and clear `selection` (implemented in the setters: `setQ`, `setStatuses`, `setConfidence`, `setTags`, `setAddedPreset` each also `set({ page: 1, selection: [] })`).

- [ ] **Step 1: api/vocabulary.ts** — append the interfaces above and:

```ts
  list: (p: VocabListParams) => {
    const qp = new URLSearchParams()
    qp.set('lang', p.lang)
    if (p.target) qp.set('target', p.target)
    for (const s of p.status ?? []) qp.append('status', s)
    if (p.confidence_min != null) qp.set('confidence_min', String(p.confidence_min))
    if (p.confidence_max != null) qp.set('confidence_max', String(p.confidence_max))
    for (const t of p.tag ?? []) qp.append('tag', t)
    if (p.q) qp.set('q', p.q)
    if (p.added_after) qp.set('added_after', p.added_after)
    if (p.sort) qp.set('sort', p.sort)
    if (p.sort_dir) qp.set('sort_dir', p.sort_dir)
    if (p.page) qp.set('page', String(p.page))
    if (p.page_size) qp.set('page_size', String(p.page_size))
    return api<VocabListResponse>(`/api/vocabulary?${qp.toString()}`)
  },
  bulk: (body: {
    item_ids: string[]
    action: 'set_known' | 'set_ignored' | 'delete' | 'add_tag'
    tag_name?: string
  }) => api<{ affected: number }>('/api/vocabulary/bulk', {
    method: 'POST', body: JSON.stringify(body),
  }),
```

- [ ] **Step 2: vocabularyStore.ts** — implement the state above with `create<VocabularyState>()((set) => ...)` (no persist middleware). `resetFilters` restores q/statuses/confidence/tags/addedPreset/page defaults and clears selection.

- [ ] **Step 3: useVocabularyQuery.ts**:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { vocabularyApi } from '@/api/vocabulary'
import type { VocabListParams } from '@/api/vocabulary'

export const VOCAB_TARGET = 'ru'

export function vocabListKey(params: VocabListParams) {
  return ['vocab-list', params] as const
}

export function useVocabList(params: VocabListParams, enabled = true) {
  return useQuery({
    queryKey: vocabListKey(params),
    queryFn: () => vocabularyApi.list(params),
    enabled,
    placeholderData: (prev) => prev,   // keep table stable while paging
  })
}

export function useVocabInvalidate() {
  const qc = useQueryClient()
  return () => void qc.invalidateQueries({ queryKey: ['vocab-list'] })
}

export function useBulkAction() {
  const invalidate = useVocabInvalidate()
  return useMutation({ mutationFn: vocabularyApi.bulk, onSuccess: invalidate })
}

export function usePatchItem() {
  const invalidate = useVocabInvalidate()
  return useMutation({
    mutationFn: (v: { itemId: string; status: 'tracked' | 'known' | 'ignored'; confidence: number | null }) =>
      vocabularyApi.patchItem('token', v.itemId, { status: v.status, confidence: v.confidence }),
    onSuccess: invalidate,
  })
}
```

- [ ] **Step 4: Route + tabs skeleton + nav.** `routes/learn.$lang.vocabulary.tsx` follows `learn.$lang.library.tsx`:

```tsx
import { createRoute, useParams, useSearch } from '@tanstack/react-router'

import { VocabularyPage } from '@/features/vocabulary/VocabularyPage'

import { learnLangRoute } from './learn.$lang'

const TABS = ['all', 'words', 'phrases', 'due'] as const
export type VocabTab = (typeof TABS)[number]

export const learnVocabularyRoute = createRoute({
  getParentRoute: () => learnLangRoute,
  path: 'vocabulary',
  validateSearch: (search: Record<string, unknown>): { tab: VocabTab } => ({
    tab: TABS.includes(search.tab as VocabTab) ? (search.tab as VocabTab) : 'all',
  }),
  component: function VocabularyView() {
    const params = useParams({ from: '/learn/$lang/vocabulary' })
    const { tab } = useSearch({ from: '/learn/$lang/vocabulary' })
    return <VocabularyPage lang={params.lang} tab={tab} />
  },
})
```

Register in `routeTree.ts`: import and add `learnVocabularyRoute` to `learnLangRoute.addChildren([...])`. In `AppTopBar.tsx` replace the placeholder comment with a «Словарь» Link (same classes as «Библиотека», `to="/learn/$lang/vocabulary"`).

`VocabularyPage.tsx` skeleton (Task 6 replaces the placeholder body):

```tsx
interface Props { lang: string; tab: 'all' | 'words' | 'phrases' | 'due' }
```

Header «Словарь»; tab row: «Все» / «Слова» as router `Link search={{ tab: 'all' | 'words' }}` with active styling, «Фразы» и «К повторению» as disabled buttons with `title="Появится позже"`; below — `useVocabList` wired from store + props (tab words/all → same params today) and a temporary `<p>Всего: {data?.total ?? '…'}</p>` placeholder.

- [ ] **Step 5: Verify + commit.** `corepack pnpm test` (existing suites green; new code compiles), `corepack pnpm lint`, `corepack pnpm build`.

```bash
git add src/features/vocabulary src/routes/learn.\$lang.vocabulary.tsx
git commit -m "feat(FLQ-6): vocabulary api layer, store, route and nav link" -- src/api/vocabulary.ts src/features/vocabulary src/routes/learn.\$lang.vocabulary.tsx src/routeTree.ts src/components/AppTopBar.tsx
```

---

### Task 6: VocabularyTable + pagination + inline picker

**Files:**
- Create: `frontend/src/features/vocabulary/VocabularyTable.tsx`
- Modify: `frontend/src/features/vocabulary/VocabularyPage.tsx`
- Test: `frontend/src/features/vocabulary/VocabularyTable.test.tsx`

**Interfaces:**
- `VocabularyTable` props:

```tsx
interface Props {
  items: VocabListItem[]
  selection: string[]
  onToggleSelected: (id: string) => void
  onSelectPage: (ids: string[]) => void      // header checkbox
  onClearSelection: () => void
  onPick: (itemId: string, status: 'tracked' | 'known' | 'ignored', confidence: number | null) => void
  onOpenTerm: (item: VocabListItem) => void
}
```

- Columns per spec §5.2: checkbox / Термин (button opens card; chips: pos + tags below) / Перевод (`primary_translation.text` or «—») / Контекст (italic, quoted, truncate ~80 chars) / `ConfidencePicker size="sm"`.
- Header checkbox: checked when every page item selected; click → all selected ? clearSelection : selectMany(page ids).
- `onPick` → `usePatchItem` mutation in the page.
- Pagination controls in the page footer: `‹ N ›` buttons + «Всего: N», page-size select 25/50/100.

- [ ] **Step 1: Write failing tests** — render `VocabularyTable` with two mock items (one with translation/tags/pos/context, one bare): asserts columns rendered («—» for missing translation), term button fires `onOpenTerm`, row picker «Уровень 3» fires `onPick(id, 'tracked', 3)`, header checkbox fires `onSelectPage` with both ids, row checkbox fires `onToggleSelected`. (Write concrete test code following `TranslationFields.test.tsx` style; mock items typed as `VocabListItem`.)

- [ ] **Step 2: Implement the table** (plain `<table>` for ≥md; mobile variant comes in Task 9 — wrap the table in `hidden md:block` now). Truncate context: `context.length > 80 ? context.slice(0, 80) + '…' : context`, render as `«{text}»` italic muted. Term cell: `<button>` with the term text bold, chips row under it (pos chip gray, tag chips outlined).

- [ ] **Step 3: Wire into VocabularyPage**: replace the placeholder body — loading skeleton (`data === undefined && isLoading`: 5 gray rows, `data-testid="vocab-skeleton"`), table when items, pagination footer, `usePatchItem().mutate({ itemId, status, confidence })` for `onPick`. Keep selection in the store.

- [ ] **Step 4: Run `corepack pnpm test` + lint.** **Step 5: Commit** scoped to the three files.

```bash
git add src/features/vocabulary/VocabularyTable.tsx src/features/vocabulary/VocabularyTable.test.tsx
git commit -m "feat(FLQ-6): vocabulary table with inline picker and pagination" -- src/features/vocabulary/VocabularyTable.tsx src/features/vocabulary/VocabularyTable.test.tsx src/features/vocabulary/VocabularyPage.tsx
```

---

### Task 7: Toolbar — search + FilterPopover + page size

**Files:**
- Create: `frontend/src/features/vocabulary/FilterPopover.tsx`
- Modify: `frontend/src/features/vocabulary/VocabularyPage.tsx`
- Test: `frontend/src/features/vocabulary/FilterPopover.test.tsx` + extend page-level test

**Requirements (spec §5.3):**
- Search input (icon, placeholder «Поиск в словаре»), local state debounced **300ms** → `store.setQ` (which resets page/selection). Test with `vi.useFakeTimers()`.
- FilterPopover: trigger button «Фильтры»; panel is a locally-positioned `absolute` card (no new radix dep) with: status checkboxes (Отслеживаемые/Изученные/Игнорируемые), confidence range as two number selects 1..4 (disabled unless `tracked` checked; «от»/«до»), tag input (Enter adds chip, ✕ removes), date preset radio (7 дней/30 дней/Всё время), «Сбросить» button → `store.resetFilters()`. Click-outside closes (document mousedown listener).
- `addedPreset → added_after` mapping lives in VocabularyPage: `'7d' → new Date(Date.now() - 7*86400e3).toISOString()`, `'30d'` similarly, `'all'` → undefined.
- Page-size select (25/50/100) in the toolbar right corner.

- [ ] Steps: failing tests (popover interactions update the store: check/uncheck status, add tag chip, reset) → implement → full `corepack pnpm test` + lint → commit:

```bash
git add src/features/vocabulary/FilterPopover.tsx src/features/vocabulary/FilterPopover.test.tsx
git commit -m "feat(FLQ-6): vocabulary search and filter popover" -- src/features/vocabulary/FilterPopover.tsx src/features/vocabulary/FilterPopover.test.tsx src/features/vocabulary/VocabularyPage.tsx
```

---

### Task 8: Selection bulk actions

**Files:**
- Create: `frontend/src/features/vocabulary/BulkActionsMenu.tsx`
- Modify: `frontend/src/features/vocabulary/VocabularyPage.tsx`
- Test: `frontend/src/features/vocabulary/BulkActionsMenu.test.tsx`

**Requirements (spec §5.3):**

```tsx
interface Props {
  count: number                       // selection size; menu disabled when 0
  onAction: (action: 'set_known' | 'set_ignored' | 'delete' | 'add_tag', tagName?: string) => void
}
```

- Dropdown (reuse `components/ui/dropdown-menu.tsx`): «Отметить known», «Отметить ignored», «Добавить тег…» (opens inline input + confirm button inside the menu), «Удалить из словаря» (destructive item).
- Delete opens a confirm `Dialog` (reuse `components/ui/dialog.tsx`): «Удалить {N} слов? Переводы, заметки и теги будут удалены» + «Удалить»/«Отмена».
- Page wiring: `useBulkAction().mutateAsync({ item_ids: selection, action, tag_name })` → on success `clearSelection()`; delete success → transient toast «Удалено N» (simple fixed-position div with 4s timeout, pattern from ReaderPage's `bulk-error`).

- [ ] Steps: failing tests (menu disabled at count 0; known action fires callback; delete requires confirm — callback NOT fired until confirm clicked; add-tag passes the typed tag) → implement → full test + lint → commit:

```bash
git add src/features/vocabulary/BulkActionsMenu.tsx src/features/vocabulary/BulkActionsMenu.test.tsx
git commit -m "feat(FLQ-6): vocabulary bulk actions with delete confirm" -- src/features/vocabulary/BulkActionsMenu.tsx src/features/vocabulary/BulkActionsMenu.test.tsx src/features/vocabulary/VocabularyPage.tsx
```

---

### Task 9: WordCard integration, empty/error states, mobile cards

**Files:**
- Modify: `frontend/src/features/reader/WordCard.tsx`, `frontend/src/features/reader/useWordCard.ts` (optional lessonId)
- Create: `frontend/src/features/vocabulary/VocabularyCardList.tsx` (mobile)
- Modify: `frontend/src/features/vocabulary/VocabularyPage.tsx`
- Test: extend `frontend/src/features/reader/WordCard.test.tsx` + `frontend/src/features/vocabulary/VocabularyPage.test.tsx` (new)

**Requirements:**
1. WordCard `lessonId` becomes `string | null` (spec §5.4): `useWordCardMutations` opts `lessonId: string | null`; `invalidate()` skips `['reader-statuses', ...]` when null; the AI query passes `lesson_id: lessonId ?? undefined`. ReaderPage keeps passing the real id — no change there. WordCard test: add one test rendering with `lessonId={null}` asserting lookup renders and no crash; assert `aiApi.translate` called WITHOUT `lesson_id` key (`expect.not.objectContaining` or check call args).
2. VocabularyPage: clicking a term sets `selectedItem`; render `<WordCard word={{ t: item.text, n: item.text, i: -1 }} lang={lang} target={VOCAB_TARGET} lessonId={null} sentenceText={null} onClose={...} />`; on close also `useVocabInvalidate()()` (status may have changed in the card).
3. States (spec §5.5): empty-default («В словаре пока пусто» + CTA «Перейти в библиотеку» Link) shown when `total === 0` AND filters are at defaults (store exposes `filtersAreDefault()` selector); filtered-empty («Ничего не найдено по текущим фильтрам» + «Сбросить фильтры» → `resetFilters`); error → inline alert + «Повторить» (`refetch`).
4. Mobile: `VocabularyCardList` rendered in `md:hidden` wrapper — card per item: term + translation on one row, chips, quoted context, footer `ConfidencePicker size="sm"` + selection checkbox top-right. Same callbacks as the table.

- [ ] Steps: failing tests (VocabularyPage.test.tsx with mocked `@/api/vocabulary`: empty-default state with CTA; filtered-empty appears when store has q set; term click renders word-card testid — mock lookup too; WordCard null-lessonId test) → implement → full `corepack pnpm test` + lint + build → commit:

```bash
git add src/features/vocabulary/VocabularyCardList.tsx src/features/vocabulary/VocabularyPage.test.tsx
git commit -m "feat(FLQ-6): wordcard on vocabulary page, states and mobile cards" -- src/features/reader/WordCard.tsx src/features/reader/useWordCard.ts src/features/reader/WordCard.test.tsx src/features/vocabulary/VocabularyCardList.tsx src/features/vocabulary/VocabularyPage.tsx src/features/vocabulary/VocabularyPage.test.tsx
```

---

### Task 10: UI-doc revision + full verification pass

**Files:**
- Modify: `docs/ui/vocabulary.md` (§8 picker revision; §4/§5 deferred-features notes per spec §8)

- [ ] **Step 1: Doc revision.** In `docs/ui/vocabulary.md`: §8 — replace the `0..5` picker description with `🗑 [1][2][3][4] ✓` and a pointer to FLQ-5 §2 (0 системный, 5 — потолок SRS); §4 — mark Импорт/Экспорт (FLQ-14) and Review (FLQ-7) as «после соответствующих задач»; §5 — mark Фразы/К повторению tabs as disabled until FLQ-7/phrase increment; §6.1 — note «поиск по переводу: принято». Commit:

```bash
git commit -m "docs(FLQ-6): revise vocabulary ui spec to match shipped picker" -- docs/ui/vocabulary.md
```

- [ ] **Step 2: Backend gates.** From `backend/`: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright` — all green.

- [ ] **Step 3: Frontend gates.** From `frontend/`: `corepack pnpm test && corepack pnpm lint && corepack pnpm build` — all green.

- [ ] **Step 4: Manual smoke (controller, dev stack).** postgres:5433 + redis up, `uv run flinq serve`, `uv run flinq worker`, `corepack pnpm dev`. Then: «Словарь» link in the top bar → page opens with items saved during earlier sessions; search by term and by translation; filter to known-only; inline picker level change reflects in the reader highlight after revisit; select two items → bulk «Отметить known»; bulk delete one with confirm; term click opens WordCard (no lesson context, AI info-note); mobile viewport (resize to 375px) shows card list.
Expected: behaviours match spec §2–§5.
