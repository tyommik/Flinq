# FLQ-6.2 — Vocabulary Provenance + LingQ Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Words auto-created by the reader's page-turn bulk-known are hidden from the vocabulary by default (`token_items.added_by` provenance with promotion on explicit actions), and the vocabulary page is restyled to the Figma mock (card rows, restyled shared picker, segmented tabs, numbered pagination, sort control).

**Architecture:** Backend first (migration 0009 + bulk writer, then promotion semantics + `added_by` filter/param). Frontend: provenance wiring (store/api/filter checkbox), then visual layers bottom-up: CSS tokens + ConfidencePicker restyle → card rows → segmented tabs/toolbar → pagination/sort.

**Tech Stack:** unchanged (FastAPI + SQLAlchemy 2 async + Alembic; React 19 + TS strict + TanStack Query + Zustand; pytest + testcontainers; Vitest).

**Spec:** `.superpowers/specs/2026-07-11-vocabulary-provenance-polish-design.md` — binding. Branch: `feature/FLQ-6-vocabulary-page` (continue on it).

## Global Constraints

- Commits: conventional, English imperative ≤72 chars, why in body, NO Co-Authored-By, scoped `git commit -- <paths>` (git add new files first).
- Backend gates per task: `uv run ruff format <files>`, `uv run ruff check .`, `uv run pyright` (0 errors), full `uv run pytest -q`. Frontend: `corepack pnpm test`, `corepack pnpm lint`; `corepack pnpm build` where routes/CSS change.
- UNICODE: Cyrillic byte-for-byte; «ИСХОДНЫЙ ТЕКСТ», «Ещё действия», «Показать:», «Показывать авто-изученные», «Сначала новые/старые», «А–Я»/«Я–А» (EN DASH U+2013).
- Behavioral test assertions must survive restyles — update label/class assertions, never weaken behavior checks.
- `added_by` values are exactly `'user' | 'bulk'`; API param `added_by=user|all`, default `user`.
- Working dirs: backend/ and frontend/ respectively.

---

### Task 1: Backend — `added_by` column, migration 0009 with backfill, bulk writer

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/models.py` (TokenItem)
- Create: `backend/migrations/versions/0009_item_provenance.py`
- Modify: `backend/src/flinq/modules/reader_state/bulk.py`
- Test: `backend/tests/modules/test_vocabulary_provenance.py` (new)

**Interfaces:**
- Produces: `TokenItem.added_by: Mapped[str]` (`'user'|'bulk'`, default `'user'`); bulk_mark_known writes `'bulk'`. Task 2 relies on the field name `added_by`.

- [ ] **Step 1: Model.** In `TokenItem` add after `confidence`:

```python
    added_by: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
```

and to `__table_args__` (keep existing entries):

```python
        CheckConstraint("added_by IN ('user', 'bulk')", name="ck_token_items_added_by"),
```

- [ ] **Step 2: Migration.** Create `backend/migrations/versions/0009_item_provenance.py`:

```python
"""token item provenance: added_by user|bulk with bulk-known backfill

Revision ID: 0009_item_provenance
Revises: 0008_translation_variants
Create Date: 2026-07-11 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_item_provenance"
down_revision: str | Sequence[str] | None = "0008_translation_variants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "token_items",
        sa.Column("added_by", sa.String(length=16), nullable=False, server_default="user"),
    )
    op.create_check_constraint(
        "ck_token_items_added_by", "token_items", "added_by IN ('user', 'bulk')"
    )
    # Backfill: items created by page-turn bulk-known actions (FLQ-4) are
    # provenance 'bulk'. bulk_actions.payload_json->'token_item_ids' lists
    # exactly the ids each action created (reader_state/bulk.py); undone
    # actions already deleted their rows, so the update is a no-op for them.
    op.execute(
        sa.text(
            """
            UPDATE token_items
            SET added_by = 'bulk'
            WHERE id IN (
                SELECT (jsonb_array_elements_text(payload_json->'token_item_ids'))::uuid
                FROM bulk_actions
                WHERE action_type = 'bulk_known' AND undone_at IS NULL
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint("ck_token_items_added_by", "token_items", type_="check")
    op.drop_column("token_items", "added_by")
```

- [ ] **Step 3: Bulk writer + undo guard.** In `reader_state/bulk.py` `bulk_mark_known`, add to each values dict (after `"confidence": None,`):

```python
                        "added_by": "bulk",
```

In `undo_bulk_action`, extend the delete's WHERE with `TokenItem.added_by == "bulk"` (alongside the existing `status == "known"` guard): once a user explicitly claims a word (promotion in Task 2 — e.g. added a tag to a page-turn word while it is still `known`), the reader's Ctrl+Z must not delete their record.

- [ ] **Step 4: Failing tests.** Create `backend/tests/modules/test_vocabulary_provenance.py` (helpers `_make_user`, `_clean` copied per file-local convention — clean `PersonalTranslation, PersonalNote, ItemTag, TokenItem, BulkAction, Lesson`; import `BulkAction` from reader_state.models, `Lesson`, `LessonSegment`, `LessonTokenOccurrence` from lesson_library.models, `bulk` module from `flinq.modules.reader_state import bulk`):

```python
async def _lesson_with_words(s: AsyncSession, user_id: uuid.UUID, words: list[str]) -> Lesson:
    lesson = Lesson(
        owner_user_id=user_id, language_code="pt", title="L", raw_text=" ".join(words),
        status="ready",
    )
    s.add(lesson)
    await s.flush()
    seg = LessonSegment(
        lesson_id=lesson.id, ordinal=0, segment_type="sentence",
        text=" ".join(words), start_char_offset=0, end_char_offset=100,
    )
    s.add(seg)
    await s.flush()
    for i, w in enumerate(words):
        s.add(
            LessonTokenOccurrence(
                lesson_id=lesson.id, segment_id=seg.id, ordinal_in_lesson=i,
                ordinal_in_segment=i, surface_text=w, normalized_text=w,
                start_char_offset=0, end_char_offset=1, is_word_like=True,
            )
        )
    await s.flush()
    return lesson


async def test_bulk_known_creates_bulk_provenance():
    async with session_scope() as s:
        user_id = await _make_user(s)
        lesson = await _lesson_with_words(s, user_id, ["cada", "porta"])
        await bulk.bulk_mark_known(
            s, user_id=user_id, lesson=lesson, from_ordinal=0, to_ordinal=1
        )
    async with session_scope() as s:
        rows = (await s.execute(select(TokenItem))).scalars().all()
    assert len(rows) == 2
    assert all(r.added_by == "bulk" for r in rows)


async def test_bulk_known_leaves_existing_user_item_untouched():
    async with session_scope() as s:
        user_id = await _make_user(s)
        s.add(
            TokenItem(
                user_id=user_id, language_code="pt", token_text="cada",
                status="tracked", confidence=2,
            )
        )
        await s.flush()
        lesson = await _lesson_with_words(s, user_id, ["cada"])
        await bulk.bulk_mark_known(
            s, user_id=user_id, lesson=lesson, from_ordinal=0, to_ordinal=0
        )
    async with session_scope() as s:
        row = (await s.execute(select(TokenItem))).scalar_one()
    assert row.added_by == "user" and row.status == "tracked" and row.confidence == 2
```

(The second test also pins that the model default for direct construction is `'user'`.)

Third test — the undo guard:

```python
async def test_undo_skips_user_claimed_items():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = TokenItem(
            user_id=user_id, language_code="pt", token_text="cada",
            status="known", confidence=None, added_by="user",
        )
        s.add(item)
        await s.flush()
        action = BulkAction(
            user_id=user_id,
            lesson_id=(await _lesson_with_words(s, user_id, ["x"])).id,
            action_type="bulk_known",
            page_fingerprint="0:0",
            payload_json={"token_item_ids": [str(item.id)]},
        )
        s.add(action)
        await s.flush()
        action_id, item_id = action.id, item.id
    async with session_scope() as s:
        undone = await bulk.undo_bulk_action(s, user_id=user_id, action_id=action_id)
    assert undone == 0
    async with session_scope() as s:
        assert await s.get(TokenItem, item_id) is not None
```

- [ ] **Step 5: Run failing → implement already done in Steps 1-3 → run green.** `uv run pytest tests/modules/test_vocabulary_provenance.py -q` → 3 passed. Apply migration to dev DB: `uv run alembic upgrade head` → `0009_item_provenance (head)`; sanity: `docker exec flinq-postgres-1 psql -U flinq -d flinq -c "select added_by, count(*) from token_items group by 1;"` — bulk-known words from smoke sessions show as `bulk`.

- [ ] **Step 6: Full suite + gates + commit.**

```bash
uv run pytest -q && uv run ruff format src/flinq/modules/vocabulary/models.py migrations/versions/0009_item_provenance.py src/flinq/modules/reader_state/bulk.py tests/modules/test_vocabulary_provenance.py && uv run ruff check . && uv run pyright
git add migrations/versions/0009_item_provenance.py tests/modules/test_vocabulary_provenance.py
git commit -m "feat(FLQ-6.2): token item provenance column with bulk backfill" -- src/flinq/modules/vocabulary/models.py migrations/versions/0009_item_provenance.py src/flinq/modules/reader_state/bulk.py tests/modules/test_vocabulary_provenance.py
```

---

### Task 2: Backend — promotion semantics, list filter, API param

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/service.py`
- Modify: `backend/src/flinq/api/vocabulary.py`
- Test: extend `backend/tests/modules/test_vocabulary_provenance.py`, extend `backend/tests/api/test_vocabulary_page.py`

**Interfaces:**
- `list_items(...)` gains keyword `added_by: str` (`'user'|'all'`); `'user'` adds `TokenItem.added_by == "user"` to conditions.
- `bulk_action` `set_known`/`set_ignored` UPDATE also sets `added_by='user'`; `add_tag` promotes via an UPDATE over `owned` before inserting tags. `delete` unchanged.
- New private helper in service.py:

```python
def _promote_to_user(item: TokenItem) -> None:
    """Explicit user action on a bulk-created item claims it (spec FLQ-6.2 §1.2)."""
    if item.added_by != "user":
        item.added_by = "user"
```

Call sites (each right after the item row is loaded/validated, before commit):
  - `create_item`: new rows get `added_by="user"` (model default covers it — pass explicitly for clarity); the idempotent existing-row branch calls `_promote_to_user(existing)`.
  - `patch_item`: `_promote_to_user(item)`.
  - `add_translation`, `update_translation`, `delete_translation`, `put_note`, `add_tag`, `remove_tag`: after `await _owned_item(...)` capture the returned item and `_promote_to_user(item)` (note `_owned_item` already returns the TokenItem — use its return value; these functions currently discard it).
- API `list_vocabulary`: add param `added_by: Literal["user", "all"] = "user"`, pass through to service.

- [ ] **Step 1: Failing tests.** Append to `test_vocabulary_provenance.py`:

```python
async def _bulk_item(s: AsyncSession, user_id: uuid.UUID, text: str = "cada") -> TokenItem:
    item = TokenItem(
        user_id=user_id, language_code="pt", token_text=text,
        status="known", confidence=None, added_by="bulk",
    )
    s.add(item)
    await s.flush()
    return item


async def test_patch_item_promotes_to_user():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = await _bulk_item(s, user_id)
        item_id = item.id
    async with session_scope() as s:
        await service.patch_item(
            s, user_id=user_id, kind="token", item_id=item_id, status="tracked", confidence=2
        )
    async with session_scope() as s:
        assert (await s.get(TokenItem, item_id)).added_by == "user"


async def test_create_item_over_bulk_promotes():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = await _bulk_item(s, user_id)
        item_id = item.id
    async with session_scope() as s:
        await service.create_item(
            s, user_id=user_id, kind="token", language_code="pt", text="cada",
            status="tracked", confidence=0,
        )
    async with session_scope() as s:
        assert (await s.get(TokenItem, item_id)).added_by == "user"


async def test_annotation_promotes_to_user():
    async with session_scope() as s:
        user_id = await _make_user(s)
        item = await _bulk_item(s, user_id)
        item_id = item.id
    async with session_scope() as s:
        await service.add_translation(
            s, user_id=user_id, kind="token", item_id=item_id,
            target_language_code="ru", translation_text="каждый", source_type="user",
        )
    async with session_scope() as s:
        assert (await s.get(TokenItem, item_id)).added_by == "user"


async def test_bulk_action_promotes_to_user():
    async with session_scope() as s:
        user_id = await _make_user(s)
        a = await _bulk_item(s, user_id, "cada")
        b = await _bulk_item(s, user_id, "porta")
        ids = [a.id, b.id]
    async with session_scope() as s:
        await service.bulk_action(
            s, user_id=user_id, item_ids=ids, action="set_ignored", tag_name=None
        )
    async with session_scope() as s:
        rows = (await s.execute(select(TokenItem))).scalars().all()
    assert all(r.added_by == "user" for r in rows)


async def test_list_items_filters_added_by():
    async with session_scope() as s:
        user_id = await _make_user(s)
        await _bulk_item(s, user_id, "cada")
        s.add(
            TokenItem(
                user_id=user_id, language_code="pt", token_text="porta",
                status="tracked", confidence=1,
            )
        )
        await s.flush()
    kw = _defaults()  # reuse the Task-1-file defaults helper or copy from test_vocabulary_list.py
    async with session_scope() as s:
        items, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 1 and items[0].text == "porta"
    kw["added_by"] = "all"
    async with session_scope() as s:
        _, total = await service.list_items(s, user_id=user_id, language_code="pt", **kw)
    assert total == 2
```

(`list_items` gains the kwarg with a DEFAULT — `added_by: str = "user"` — so existing tests and the `_defaults()` helper stay valid unchanged; copy `_defaults()` from `test_vocabulary_list.py` into this file as-is and override `kw["added_by"] = "all"` where the test needs it. `test_vocabulary_list.py` itself needs NO edits.)

Append to `tests/api/test_vocabulary_page.py`:

```python
async def test_list_added_by_param():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        await _create_item(c, h, "cada")  # explicit create → added_by user
        r = await c.get("/api/vocabulary", params={"lang": "pt", "added_by": "all"})
        assert r.status_code == 200 and r.json()["total"] == 1
        r = await c.get("/api/vocabulary", params={"lang": "pt", "added_by": "bogus"})
        assert r.status_code == 422
```

- [ ] **Step 2: Run failing.** `uv run pytest tests/modules/test_vocabulary_provenance.py tests/api/test_vocabulary_page.py -q` → new tests FAIL.

- [ ] **Step 3: Implement** per the Interfaces block: `_promote_to_user`; `list_items(..., added_by: str = "user")` with `if added_by == "user": conditions.append(TokenItem.added_by == "user")`; `bulk_action` update `.values(status=..., confidence=None, added_by="user")` and for `add_tag` a preceding `await session.execute(update(TokenItem).where(TokenItem.id.in_(owned)).values(added_by="user"))`; capture `item = await _owned_item(...)` + `_promote_to_user(item)` in the six annotation functions and `patch_item`; `create_item` explicit `added_by="user"` on the new row + promote in the existing-row branch. API route gains `added_by: Literal["user", "all"] = "user"` passed through.

- [ ] **Step 4: Full suite + gates + commit** (scoped: service.py, api/vocabulary.py, the two test files).

```bash
git commit -m "feat(FLQ-6.2): provenance promotion and added_by list filter" -- src/flinq/modules/vocabulary/service.py src/flinq/api/vocabulary.py tests/modules/test_vocabulary_provenance.py tests/modules/test_vocabulary_list.py tests/api/test_vocabulary_page.py
```

---

### Task 3: Frontend — added_by wiring (api, store, filter checkbox)

**Files:**
- Modify: `frontend/src/api/vocabulary.ts` (`VocabListParams.added_by?: 'user' | 'all'`; `if (p.added_by) qp.set('added_by', p.added_by)`)
- Modify: `frontend/src/features/vocabulary/vocabularyStore.ts`
- Modify: `frontend/src/features/vocabulary/VocabularyPage.tsx`
- Modify: `frontend/src/features/vocabulary/FilterPopover.tsx`
- Test: extend `FilterPopover.test.tsx` + `VocabularyPage.test.tsx`

**Requirements:**
- Store: `showAuto: boolean` (default false), `setShowAuto(v)` — resets page/selection like other filter setters; `resetFilters` sets false; `filtersAreDefault` includes `!s.showAuto`.
- Page: `added_by: showAuto ? 'all' : 'user'` in `useVocabList` params.
- FilterPopover: new checkbox row «Показывать авто-изученные» (helper text «слова, отмеченные изученными при листании») wired to `showAuto`.
- Tests: checkbox toggles store + page sends `added_by=all` when store showAuto=true (assert via mocked `vocabularyApi.list` call args); default sends `added_by:'user'`.

- [ ] Steps: failing tests → implement → full `corepack pnpm test` + lint → commit:

```bash
git commit -m "feat(FLQ-6.2): show-auto filter wired to added_by param" -- src/api/vocabulary.ts src/features/vocabulary/vocabularyStore.ts src/features/vocabulary/VocabularyPage.tsx src/features/vocabulary/FilterPopover.tsx src/features/vocabulary/FilterPopover.test.tsx src/features/vocabulary/VocabularyPage.test.tsx
```

---

### Task 4: Frontend — CSS tokens + ConfidencePicker restyle

**Files:**
- Modify: `frontend/src/index.css` (token block from spec §2.1, verbatim)
- Modify: `frontend/src/components/ConfidencePicker.tsx`
- Test: `frontend/src/components/ConfidencePicker.test.tsx` (update class assertions)

**Requirements (spec §2.3):**
- Sizes: md → pills `h-8 w-8` (32px), sm → `h-7 w-7` (28px); check/trash keep proportional padding.
- Pills: default `border border-[var(--vocab-picker-border)] bg-white text-[var(--vocab-muted-fg)] hover:bg-accent`; active level: `bg-[var(--vocab-picker-active-bg)] text-[var(--vocab-picker-active-fg)] border-transparent font-semibold`.
- `✓` active (known): `bg-[var(--vocab-known-bg)] text-white border-transparent`; inactive: bordered like pills.
- `🗑` active (ignored): keep `border-foreground` (unchanged).
- aria-labels/titles/behavior unchanged. WordCard/table/mobile pick the new look automatically (shared component) — их тесты по ролям не трогать.
- ConfidencePicker.test.tsx: replace the `border-primary` active-class assertions with the new tokens (e.g. `toContain('--vocab-picker-active-bg')`), keep the confidence-0-no-highlight and onSelect behavior tests as-is.

- [ ] Steps: update tests to pin the NEW classes (fail) → implement → full test + lint + build → commit:

```bash
git commit -m "feat(FLQ-6.2): figma tokens and confidence picker restyle" -- src/index.css src/components/ConfidencePicker.tsx src/components/ConfidencePicker.test.tsx
```

---

### Task 5: Frontend — card rows redesign

**Files:**
- Modify: `frontend/src/features/vocabulary/VocabularyTable.tsx` (rewrite render; props contract UNCHANGED)
- Modify: `frontend/src/features/vocabulary/VocabularyCardList.tsx` (apply tokens)
- Modify: `frontend/src/features/vocabulary/VocabularyPage.tsx` (page bg + Inter font-stack wrapper)
- Test: `VocabularyTable.test.tsx` (update label assertions, keep behavior)

**Requirements (spec §2.2):**
- Desktop (`hidden md:block`): header row (checkbox select-all + uppercase labels `ТЕРМИН/ПЕРЕВОД/ИСХОДНЫЙ ТЕКСТ/СТАТУС`, 11px semibold tracking-wide `text-[var(--vocab-header-fg)]`), then a stack of card rows: `rounded-lg border border-[var(--vocab-card-border)] bg-white`, gap-2, internal grid `grid-cols-[40px_minmax(240px,1fr)_minmax(200px,0.8fr)_minmax(240px,1fr)_260px] items-center px-4 py-3` (implementer may tune, keep the five zones aligned with the header).
- Term: 15px semibold `text-[var(--vocab-term-fg)]`, still a button (onOpenTerm); chips row below: POS chip `bg-[var(--vocab-chip-pos-bg)]`, tag chips `bg-[var(--vocab-chip-gram-bg)]`, 11px, rounded, h-5 px-1.5.
- Translation: `🇷🇺` (flag by `primary_translation.target_language_code`: ru→🇷🇺, en→🇬🇧, pt→🇧🇷; helper `flagFor(code)`) + text `text-[var(--vocab-translation-fg)]`; missing → «—» muted.
- Source text: 13px `text-[var(--vocab-muted-fg)]`, quoted «…», `line-clamp-2` (keep the 80-char JS truncation as-is).
- Semantics: keep `role`-discoverable structure — plain divs with the existing aria-labels on checkboxes/buttons; tests query by role button/checkbox and text, so replace table-role queries in tests if any relied on `row`/`columnheader` roles (check the test file; update queries to `getByText`/`getByRole('checkbox'|'button')`).
- Page container: wrap the vocabulary page content in `bg-[var(--vocab-page-bg)]` section with `[font-family:'Inter',system-ui,sans-serif]`; page heading stays.
- Tests to update: «Контекст» → «ИСХОДНЫЙ ТЕКСТ» (and СТАТУС header presence), everything else behavioral stays green.

- [ ] Steps: adjust tests first (fail) → rewrite render → full test + lint + build → commit:

```bash
git commit -m "feat(FLQ-6.2): vocabulary card rows per figma" -- src/features/vocabulary/VocabularyTable.tsx src/features/vocabulary/VocabularyTable.test.tsx src/features/vocabulary/VocabularyCardList.tsx src/features/vocabulary/VocabularyPage.tsx
```

---

### Task 6: Frontend — segmented tabs + toolbar rework

**Files:**
- Modify: `frontend/src/features/vocabulary/VocabularyPage.tsx`
- Modify: `frontend/src/features/vocabulary/BulkActionsMenu.tsx` (trigger label)
- Test: `VocabularyPage.test.tsx`, `BulkActionsMenu.test.tsx` (label updates)

**Requirements (spec §2.4):**
- Tabs → segmented control: track `bg-[var(--vocab-subtabs-track)] rounded-lg p-0.5 inline-flex`; segments h-8 px-6 text-[13px]; active: `bg-white border border-[#C7CCD4] shadow-sm rounded-md font-semibold text-[var(--vocab-term-fg)]`; inactive: `text-[var(--vocab-muted-fg)]`; Все/Слова remain router Links, Фразы/К повторению disabled buttons with the same tooltip.
- Toolbar right-aligned in the same row as the segmented control: «⌕»-prefixed SearchInput (keep the persistent input — spec allows it on desktop), «Фильтры» trigger restyled as text button (`⊟ Фильтры`), bulk trigger renamed «Ещё действия» (`Ещё действия (N) ▾` via the dropdown chevron; disabled at 0 unchanged).
- BulkActionsMenu.test.tsx: trigger name assertions «Действия» → «Ещё действия»; behavior tests unchanged. VocabularyPage tests: update any trigger-name queries.

- [ ] Steps: update tests (fail) → implement → full test + lint → commit:

```bash
git commit -m "feat(FLQ-6.2): segmented tabs and text toolbar" -- src/features/vocabulary/VocabularyPage.tsx src/features/vocabulary/VocabularyPage.test.tsx src/features/vocabulary/BulkActionsMenu.tsx src/features/vocabulary/BulkActionsMenu.test.tsx
```

---

### Task 7: Frontend — numbered pagination, «Показать:», page clamp, sort dropdown

**Files:**
- Create: `frontend/src/features/vocabulary/PaginationNumbers.tsx` + `PaginationNumbers.test.tsx`
- Modify: `frontend/src/features/vocabulary/VocabularyPage.tsx`, `frontend/src/features/vocabulary/vocabularyStore.ts` (setSort resets page/selection)
- Test: extend `VocabularyPage.test.tsx`

**Requirements (spec §3):**
- `PaginationNumbers({ page, totalPages, onPage })`: renders `‹ 1 … p-1 p p+1 … N ›`; window rule: always 1 and N; neighbors of current; `…` (non-interactive) when gaps; current = dark circle `bg-[var(--vocab-term-fg)] text-white h-5 w-5 rounded-full text-xs`, others plain `text-[var(--vocab-muted-fg)]`; ‹/› disabled at bounds (aria-labels «Предыдущая страница»/«Следующая страница» reused).
- Placement: in the list header row right side, together with «Показать: 25 ▾» (page-size Select gets a visible «Показать:» label). Remove the old bottom prev/next block; «Всего: N» moves next to «Показать:».
- Clamp: in VocabularyPage add `useEffect(() => { if (data && page > totalPages) setPage(totalPages) }, [data, page, totalPages, setPage])`.
- Sort dropdown in the toolbar (reuse ui/select or dropdown-menu): options «Сначала новые» (created_at desc, default) / «Сначала старые» (created_at asc) / «А–Я» (text asc) / «Я–А» (text desc) → `setSort(sort, sortDir)`; store `setSort` now also `page: 1, selection: []`.
- Tests: PaginationNumbers unit (window/ellipsis/current/bounds: totalPages=1, =7 current=4, =2); page-level: sort select changes `vocabularyApi.list` args and resets page; clamp effect (mock data with total shrinking) — assert setPage called / list requested with page=totalPages.

- [ ] Steps: failing tests → implement → full test + lint + build → commit:

```bash
git add src/features/vocabulary/PaginationNumbers.tsx src/features/vocabulary/PaginationNumbers.test.tsx
git commit -m "feat(FLQ-6.2): numbered pagination, sort control, page clamp" -- src/features/vocabulary/PaginationNumbers.tsx src/features/vocabulary/PaginationNumbers.test.tsx src/features/vocabulary/VocabularyPage.tsx src/features/vocabulary/VocabularyPage.test.tsx src/features/vocabulary/vocabularyStore.ts
```

---

### Task 8: Full verification pass (controller)

- [ ] **Step 1: Backend gates.** `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright` — green.
- [ ] **Step 2: Frontend gates.** `corepack pnpm test && corepack pnpm lint && corepack pnpm build` — green.
- [ ] **Step 3: Manual smoke (dev stack, migration applied).**
  1. В ридере пролистать страницу «Далее» → открыть словарь: новые слова НЕ видны; фильтры → «Показывать авто-изученные» → видны.
  2. Поставить одному из них уровень пикером в ридере → слово появляется в словаре без чекбокса (промоушен).
  3. Визуальная сверка с макетом: карточки-строки, жёлтый активный уровень, зелёная ✓, segmented-табы, капс-заголовки, «ИСХОДНЫЙ ТЕКСТ», флажок у перевода, «Ещё действия», «Показать: 25», нумерованная пагинация (создать >25 items или page_size=25 с 26+ словами через чекбокс авто-изученных).
  4. Sort «А–Я» пересортировывает; удаление последнего элемента на последней странице клампит page.
  5. WordCard-футер тоже в новом стиле пикера.
