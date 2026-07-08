# FLQ-18 — WordCard Increment 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translation multi-fields saved on Enter (replacing debounced autosave), server-computed primary with PATCH/DELETE translation endpoints and text dedupe, contextual AI with proper disabled/error states, ignored layout, and FLQ-18 cleanups.

**Architecture:** Backend first: migration 0008 (dedupe + unique index), service-layer add/update/delete with server-side `is_primary`, then API routes. Frontend second: a standalone `TranslationFields` component, WordCard integration (debounce removal, suggestions = AI+dict only), AI context threading from ReaderPage, layouts.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic; React 19 + TS strict + TanStack Query v5 + Zustand 5; pytest + testcontainers; Vitest + @testing-library.

**Spec:** `.superpowers/specs/2026-07-08-wordcard-increment-2-design.md` — binding. Section references (§) below point there.

## Global Constraints

- `flinq.core.textnorm.normalize_token` is FROZEN — do not touch; `token_text` stays the join key.
- Commits: conventional, English imperative subject ≤72 chars, body explains why, NO Co-Authored-By, one logical change per commit, always scoped: `git commit -m "..." -- <exact paths>`.
- Before every backend commit run `uv run ruff format <changed files>` then `uv run ruff check .` and `uv run pyright` — CI runs `ruff format --check` and fails on unformatted files (this exact failure shipped in FLQ-5).
- Backend tests: `uv run pytest` needs Docker (testcontainers). No per-test rollback — file-local autouse cleanup fixtures delete rows after each test (see existing `_clean` fixtures).
- Frontend: `corepack pnpm test`, `corepack pnpm lint` must pass.
- UNICODE WARNING: copy Cyrillic string literals byte-for-byte; never "simplify" unicode in tests or code.
- Working dir: backend commands from `backend/`, frontend from `frontend/`.
- The dev DB may hold real duplicate rows — migration 0008 must dedupe before creating the unique index.
- API error contract: 404 unknown/foreign item or translation, 409 duplicate text on PATCH, 200 (not 201) when POST returns an existing translation.

---

### Task 1: Migration 0008 + unique text index on the model

**Files:**
- Create: `backend/migrations/versions/0008_translation_variants.py`
- Modify: `backend/src/flinq/modules/vocabulary/models.py` (PersonalTranslation `__table_args__`)

**Interfaces:**
- Produces: DB unique index `uq_personal_translations_text` on `(owner_user_id, item_kind, item_id, target_language_code, translation_text)`; Tasks 2–3 rely on "duplicate text per item/target is impossible".

- [ ] **Step 1: Add the unique index to the model**

In `backend/src/flinq/modules/vocabulary/models.py`, extend `PersonalTranslation.__table_args__` (keep the two existing entries) with:

```python
        Index(
            "uq_personal_translations_text",
            "owner_user_id",
            "item_kind",
            "item_id",
            "target_language_code",
            "translation_text",
            unique=True,
        ),
```

- [ ] **Step 2: Write the migration**

Create `backend/migrations/versions/0008_translation_variants.py`:

```python
"""translation variants: dedupe exact duplicates, unique text per item/target

Revision ID: 0008_translation_variants
Revises: 0007_vocabulary_card
Create Date: 2026-07-08 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_translation_variants"
down_revision: str | Sequence[str] | None = "0007_vocabulary_card"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Data fix: drop exact duplicates, keeping the primary row if any,
    # otherwise the earliest. Must run before the unique index lands.
    op.execute(
        sa.text(
            """
            DELETE FROM personal_translations pt
            USING (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY owner_user_id, item_kind, item_id,
                                        target_language_code, translation_text
                           ORDER BY is_primary DESC, created_at ASC, id ASC
                       ) AS rn
                FROM personal_translations
            ) ranked
            WHERE pt.id = ranked.id AND ranked.rn > 1
            """
        )
    )
    op.create_index(
        "uq_personal_translations_text",
        "personal_translations",
        ["owner_user_id", "item_kind", "item_id", "target_language_code", "translation_text"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_personal_translations_text", table_name="personal_translations")
```

- [ ] **Step 3: Apply to the dev DB and verify**

Run from `backend/`: `uv run alembic upgrade head`
Expected: `0007_vocabulary_card -> 0008_translation_variants` applied.
Verify no duplicates remain: `uv run alembic current` shows `0008_translation_variants (head)`.

- [ ] **Step 4: Run the existing suite**

Run: `uv run pytest tests/modules/test_vocabulary_service.py tests/api/test_vocabulary.py -q`
Expected: PASS (existing tests never insert duplicate texts).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format migrations/versions/0008_translation_variants.py src/flinq/modules/vocabulary/models.py
uv run ruff check . && uv run pyright
git commit -m "feat(FLQ-18): dedupe personal translations and enforce unique text" -- migrations/versions/0008_translation_variants.py src/flinq/modules/vocabulary/models.py
```

---

### Task 2: Service — server-side primary, text dedupe, update/delete

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/service.py`
- Modify: `backend/src/flinq/api/vocabulary.py` (only the `add_translation` call site — keep route/schema as-is for now; full API rework is Task 3)
- Test: `backend/tests/modules/test_vocabulary_service.py`

**Interfaces:**
- Consumes: models from Task 1.
- Produces (Task 3 relies on these exact signatures):
  - `async def add_translation(session, *, user_id, kind, item_id, target_language_code, translation_text, source_type) -> tuple[PersonalTranslation, bool]` — `(row, created)`; dedupes by text; `is_primary` computed server-side (True iff no rows for the (owner, item, target) yet). The `is_primary` parameter is REMOVED.
  - `async def update_translation(session, *, user_id, kind, item_id, translation_id, translation_text) -> PersonalTranslation` — text-only edit; flips `source_type` to `"user"`; raises `DuplicateTranslation` if another variant of the same target already has that text.
  - `async def delete_translation(session, *, user_id, kind, item_id, translation_id) -> list[PersonalTranslation]` — deletes; if the row was primary, promotes the earliest remaining variant of the same target; returns the item's remaining translations ordered `(is_primary desc, created_at asc)`.
  - New exceptions `TranslationNotFound`, `DuplicateTranslation` (module level, next to `ItemNotFound`).
- Also: `lookup()` must reuse `_list_tags` instead of its inline tag query (cleanup from FLQ-18).

- [ ] **Step 1: Write failing service tests**

In `backend/tests/modules/test_vocabulary_service.py`, DELETE the old `test_add_translation_promotes_single_primary` (its "last write wins primary" semantics is gone) and add:

```python
async def test_add_translation_first_is_primary_next_are_not():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        first, created = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="user",
        )
        assert created is True and first.is_primary is True
    async with session_scope() as s:
        second, created = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="второй",
            source_type="user",
        )
        assert created is True and second.is_primary is False


async def test_add_translation_dedupes_by_text():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        first, _ = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="user",
        )
    async with session_scope() as s:
        again, created = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="dictionary",
        )
    assert created is False and again.id == first.id


async def test_update_translation_changes_text_and_source():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        row, _ = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="dictionary",
        )
        row_id = row.id
    async with session_scope() as s:
        updated = await service.update_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            translation_id=row_id,
            translation_text="поправленный",
        )
        assert updated.translation_text == "поправленный"
        assert updated.source_type == "user"


async def test_update_translation_duplicate_text_raises():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="user",
        )
        second, _ = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="второй",
            source_type="user",
        )
        second_id = second.id
    async with session_scope() as s:
        with pytest.raises(service.DuplicateTranslation):
            await service.update_translation(
                s,
                user_id=user_id,
                kind="token",
                item_id=item_id,
                translation_id=second_id,
                translation_text="первый",
            )


async def test_delete_primary_promotes_earliest_remaining():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        first, _ = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="user",
        )
        first_id = first.id
    async with session_scope() as s:
        await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="второй",
            source_type="user",
        )
    async with session_scope() as s:
        await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="третий",
            source_type="user",
        )
    async with session_scope() as s:
        remaining = await service.delete_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            translation_id=first_id,
        )
    texts = [(t.translation_text, t.is_primary) for t in remaining]
    assert texts == [("второй", True), ("третий", False)]


async def test_delete_translation_foreign_row_raises():
    async with session_scope() as s:
        user_id = await _make_user(s)
        other_id = await _make_user(s)
    item_id = await _tracked_item(user_id)
    async with session_scope() as s:
        row, _ = await service.add_translation(
            s,
            user_id=user_id,
            kind="token",
            item_id=item_id,
            target_language_code="ru",
            translation_text="первый",
            source_type="user",
        )
        row_id = row.id
    async with session_scope() as s:
        with pytest.raises(service.ItemNotFound):
            await service.delete_translation(
                s,
                user_id=other_id,
                kind="token",
                item_id=item_id,
                translation_id=row_id,
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/modules/test_vocabulary_service.py -q`
Expected: FAIL — `add_translation` still takes `is_primary` / returns a row, and `update_translation`, `delete_translation`, `DuplicateTranslation` don't exist.

- [ ] **Step 3: Implement in service.py**

Add exceptions next to `ItemNotFound`:

```python
class TranslationNotFound(Exception):  # noqa: N818 -- matches sibling exception naming
    """Translation row does not exist or is not owned by the user/item."""


class DuplicateTranslation(Exception):  # noqa: N818 -- matches sibling exception naming
    """Another variant with the same text exists for this item/target."""
```

Replace `add_translation` and add the two new functions plus a shared row loader:

```python
async def _owned_translation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    translation_id: uuid.UUID,
) -> PersonalTranslation:
    row = await session.get(PersonalTranslation, translation_id)
    if row is None or row.owner_user_id != user_id or row.item_id != item_id:
        raise TranslationNotFound(str(translation_id))
    return row


async def _item_translations(
    session: AsyncSession, *, user_id: uuid.UUID, item_id: uuid.UUID
) -> list[PersonalTranslation]:
    return list(
        (
            await session.execute(
                select(PersonalTranslation)
                .where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == "token",
                    PersonalTranslation.item_id == item_id,
                )
                .order_by(PersonalTranslation.is_primary.desc(), PersonalTranslation.created_at)
            )
        )
        .scalars()
        .all()
    )


async def add_translation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    target_language_code: str,
    translation_text: str,
    source_type: str,
) -> tuple[PersonalTranslation, bool]:
    """Add a variant; returns (row, created).

    Dedupes by exact text: an existing row with the same text is returned
    as-is (created=False). `is_primary` is computed server-side — the first
    variant for the (owner, item, target) becomes primary (§2.2 of the spec).
    """
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    scope = (
        PersonalTranslation.owner_user_id == user_id,
        PersonalTranslation.item_kind == "token",
        PersonalTranslation.item_id == item_id,
        PersonalTranslation.target_language_code == target_language_code,
    )
    existing = (
        await session.execute(
            select(PersonalTranslation).where(
                *scope, PersonalTranslation.translation_text == translation_text
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    has_any = (
        await session.execute(select(PersonalTranslation.id).where(*scope).limit(1))
    ).scalar_one_or_none() is not None
    row = PersonalTranslation(
        owner_user_id=user_id,
        item_kind="token",
        item_id=item_id,
        target_language_code=target_language_code,
        translation_text=translation_text,
        is_primary=not has_any,
        source_type=source_type,
    )
    session.add(row)
    await session.commit()
    return row, True


async def update_translation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    translation_id: uuid.UUID,
    translation_text: str,
) -> PersonalTranslation:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    row = await _owned_translation(
        session, user_id=user_id, item_id=item_id, translation_id=translation_id
    )
    if row.translation_text == translation_text:
        return row
    duplicate = (
        await session.execute(
            select(PersonalTranslation.id).where(
                PersonalTranslation.owner_user_id == user_id,
                PersonalTranslation.item_kind == "token",
                PersonalTranslation.item_id == item_id,
                PersonalTranslation.target_language_code == row.target_language_code,
                PersonalTranslation.translation_text == translation_text,
                PersonalTranslation.id != row.id,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise DuplicateTranslation(translation_text)
    row.translation_text = translation_text
    row.source_type = "user"
    await session.commit()
    return row


async def delete_translation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    item_id: uuid.UUID,
    translation_id: uuid.UUID,
) -> list[PersonalTranslation]:
    _check_kind(kind)
    await _owned_item(session, user_id=user_id, item_id=item_id)
    row = await _owned_translation(
        session, user_id=user_id, item_id=item_id, translation_id=translation_id
    )
    was_primary = row.is_primary
    target = row.target_language_code
    await session.delete(row)
    await session.flush()
    if was_primary:
        successor = (
            await session.execute(
                select(PersonalTranslation)
                .where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == "token",
                    PersonalTranslation.item_id == item_id,
                    PersonalTranslation.target_language_code == target,
                )
                .order_by(PersonalTranslation.created_at, PersonalTranslation.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if successor is not None:
            successor.is_primary = True
    await session.commit()
    return await _item_translations(session, user_id=user_id, item_id=item_id)
```

In `lookup()`, replace the inline translations query with `_item_translations(...)` and the inline tag query with `await _list_tags(session, user_id=user_id, item_id=item.id)` (move `_list_tags` above `lookup` if needed).

- [ ] **Step 4: Adapt the one API call site (minimal shim)**

In `backend/src/flinq/api/vocabulary.py`, `add_translation` route body — the service no longer accepts `is_primary` and returns a tuple:

```python
    row, _created = await service.add_translation(
        session,
        user_id=user_id,
        kind=kind,
        item_id=item_id,
        target_language_code=body.target_language_code,
        translation_text=body.translation_text,
        source_type=body.source_type,
    )
```

(and `return _translation_out(row)` below). Route status codes/schemas unchanged in this task.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/modules/test_vocabulary_service.py tests/api/test_vocabulary.py -q`
Expected: PASS.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format src/flinq/modules/vocabulary/service.py src/flinq/api/vocabulary.py tests/modules/test_vocabulary_service.py
uv run ruff check . && uv run pyright
git commit -m "feat(FLQ-18): server-side primary, text dedupe, translation edit/delete" -- src/flinq/modules/vocabulary/service.py src/flinq/api/vocabulary.py tests/modules/test_vocabulary_service.py
```

---

### Task 3: API — PATCH/DELETE translation routes, schema cleanup

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/schemas.py`
- Modify: `backend/src/flinq/api/vocabulary.py`
- Test: `backend/tests/api/test_vocabulary.py`

**Interfaces:**
- Consumes: Task 2 service functions/exceptions.
- Produces (frontend Task 4 relies on):
  - `POST /api/vocabulary/items/{kind}/{id}/translations` — body `{target_language_code, translation_text, source_type}` (NO `is_primary`); 201 when created, 200 with the existing row when deduped.
  - `PATCH /api/vocabulary/items/{kind}/{id}/translations/{translation_id}` — body `{translation_text}`; 200 `TranslationOut`; 404 unknown; 409 duplicate text.
  - `DELETE /api/vocabulary/items/{kind}/{id}/translations/{translation_id}` — 200 `{"translations": [TranslationOut, ...]}`.
  - `_resolve` loses its unused `item_id` param (FLQ-18 cleanup).

- [ ] **Step 1: Write failing API tests**

In `backend/tests/api/test_vocabulary.py`: in `test_create_then_translate_then_lookup`, drop the `"is_primary": True` line from the POST body (schema will reject unknown fields? No — pydantic ignores extra by default, but the field is being removed; keep the test honest). Add:

```python
async def _item_with_translation(c: AsyncClient, h: dict[str, str]) -> tuple[str, str]:
    r = await c.post(
        "/api/vocabulary/items",
        headers=h,
        json={
            "kind": "token",
            "language_code": "pt",
            "text": "cada",
            "status": "tracked",
            "confidence": 0,
        },
    )
    assert r.status_code == 201
    item_id = r.json()["item_id"]
    r = await c.post(
        f"/api/vocabulary/items/token/{item_id}/translations",
        headers=h,
        json={"target_language_code": "ru", "translation_text": "первый", "source_type": "user"},
    )
    assert r.status_code == 201
    return item_id, r.json()["id"]


async def test_post_duplicate_translation_returns_200_with_existing_row():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        item_id, tr_id = await _item_with_translation(c, h)
        r = await c.post(
            f"/api/vocabulary/items/token/{item_id}/translations",
            headers=h,
            json={
                "target_language_code": "ru",
                "translation_text": "первый",
                "source_type": "dictionary",
            },
        )
        assert r.status_code == 200
        assert r.json()["id"] == tr_id


async def test_patch_translation_text_and_409_on_duplicate():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        item_id, tr_id = await _item_with_translation(c, h)
        r = await c.patch(
            f"/api/vocabulary/items/token/{item_id}/translations/{tr_id}",
            headers=h,
            json={"translation_text": "поправленный"},
        )
        assert r.status_code == 200
        assert r.json()["text"] == "поправленный" and r.json()["source_type"] == "user"
        r = await c.post(
            f"/api/vocabulary/items/token/{item_id}/translations",
            headers=h,
            json={"target_language_code": "ru", "translation_text": "второй", "source_type": "user"},
        )
        second_id = r.json()["id"]
        r = await c.patch(
            f"/api/vocabulary/items/token/{item_id}/translations/{second_id}",
            headers=h,
            json={"translation_text": "поправленный"},
        )
        assert r.status_code == 409


async def test_delete_translation_promotes_and_returns_list():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        item_id, first_id = await _item_with_translation(c, h)
        r = await c.post(
            f"/api/vocabulary/items/token/{item_id}/translations",
            headers=h,
            json={"target_language_code": "ru", "translation_text": "второй", "source_type": "user"},
        )
        assert r.status_code == 201
        r = await c.delete(
            f"/api/vocabulary/items/token/{item_id}/translations/{first_id}", headers=h
        )
        assert r.status_code == 200
        body = r.json()
        assert [t["text"] for t in body["translations"]] == ["второй"]
        assert body["translations"][0]["is_primary"] is True


async def test_translation_routes_404_on_foreign_translation():
    async with await _client() as c:
        csrf = await _register(c)
        h = {"X-CSRF-Token": csrf}
        item_id, _ = await _item_with_translation(c, h)
        missing = uuid.uuid4()
        r = await c.patch(
            f"/api/vocabulary/items/token/{item_id}/translations/{missing}",
            headers=h,
            json={"translation_text": "х"},
        )
        assert r.status_code == 404
        r = await c.delete(
            f"/api/vocabulary/items/token/{item_id}/translations/{missing}", headers=h
        )
        assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_vocabulary.py -q`
Expected: FAIL — 405 on PATCH/DELETE (routes missing), 201 on the duplicate POST.

- [ ] **Step 3: Schemas**

In `schemas.py`: remove the `is_primary: bool = True` field from `AddTranslationRequest`; add:

```python
class UpdateTranslationRequest(BaseModel):
    translation_text: str = Field(min_length=1, max_length=512)


class TranslationListResponse(BaseModel):
    translations: list[TranslationOut]
```

- [ ] **Step 4: Routes**

In `api/vocabulary.py`:
- `from fastapi import Response` (extend the existing import).
- Import `TranslationListResponse`, `UpdateTranslationRequest` from schemas.
- Change `_resolve(kind: str, item_id: uuid.UUID)` to `_resolve(kind: str)` and update all call sites (`_resolve(kind)`).
- Rework the POST route (dynamic status):

```python
@router.post("/items/{kind}/{item_id}/translations", response_model=TranslationOut)
async def add_translation(
    request: Request,
    response: Response,
    kind: Kind,
    item_id: uuid.UUID,
    body: AddTranslationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranslationOut:
    user_id = _require_user(request)
    _resolve(kind)
    try:
        row, created = await service.add_translation(
            session,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            target_language_code=body.target_language_code,
            translation_text=body.translation_text,
            source_type=body.source_type,
        )
    except service.ItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _translation_out(row)
```

- Add PATCH and DELETE:

```python
@router.patch("/items/{kind}/{item_id}/translations/{translation_id}", response_model=TranslationOut)
async def update_translation(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    translation_id: uuid.UUID,
    body: UpdateTranslationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranslationOut:
    user_id = _require_user(request)
    _resolve(kind)
    try:
        row = await service.update_translation(
            session,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            translation_id=translation_id,
            translation_text=body.translation_text,
        )
    except (service.ItemNotFound, service.TranslationNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    except service.DuplicateTranslation:
        raise HTTPException(status.HTTP_409_CONFLICT, "duplicate translation text") from None
    return _translation_out(row)


@router.delete(
    "/items/{kind}/{item_id}/translations/{translation_id}",
    response_model=TranslationListResponse,
)
async def delete_translation(
    request: Request,
    kind: Kind,
    item_id: uuid.UUID,
    translation_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranslationListResponse:
    user_id = _require_user(request)
    _resolve(kind)
    try:
        rows = await service.delete_translation(
            session,
            user_id=user_id,
            kind=kind,
            item_id=item_id,
            translation_id=translation_id,
        )
    except (service.ItemNotFound, service.TranslationNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None
    return TranslationListResponse(translations=[_translation_out(t) for t in rows])
```

- [ ] **Step 5: Run the backend suite**

Run: `uv run pytest -q`
Expected: PASS (all files).

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format src/flinq/api/vocabulary.py src/flinq/modules/vocabulary/schemas.py tests/api/test_vocabulary.py
uv run ruff check . && uv run pyright
git commit -m "feat(FLQ-18): translation PATCH/DELETE endpoints, drop client is_primary" -- src/flinq/api/vocabulary.py src/flinq/modules/vocabulary/schemas.py tests/api/test_vocabulary.py
```

---

### Task 4: Frontend API layer

**Files:**
- Modify: `frontend/src/api/vocabulary.ts`
- Modify: `frontend/src/features/reader/useWordCard.ts`

**Interfaces:**
- Consumes: Task 3 endpoints.
- Produces (Tasks 5–6 rely on):
  - `vocabularyApi.addTranslation(kind, id, { target_language_code, translation_text, source_type })` (no `is_primary`).
  - `vocabularyApi.updateTranslation(kind, id, translationId, translation_text) => Promise<TranslationOut>`
  - `vocabularyApi.deleteTranslation(kind, id, translationId) => Promise<{ translations: TranslationOut[] }>`
  - `useWordCardMutations` gains `updateTranslation` and `deleteTranslation` mutations (same `invalidate` on success); the `'token' as ItemKind` cast is gone.

- [ ] **Step 1: vocabulary.ts**

Replace `addTranslation` and append the two methods inside `vocabularyApi`:

```ts
  addTranslation: (kind: ItemKind, id: string, body: {
    target_language_code: string; translation_text: string
    source_type?: SourceType
  }) => api<TranslationOut>(`/api/vocabulary/items/${kind}/${id}/translations`, {
    method: 'POST', body: JSON.stringify(body),
  }),
  updateTranslation: (kind: ItemKind, id: string, translationId: string, translation_text: string) =>
    api<TranslationOut>(`/api/vocabulary/items/${kind}/${id}/translations/${translationId}`, {
      method: 'PATCH', body: JSON.stringify({ translation_text }),
    }),
  deleteTranslation: (kind: ItemKind, id: string, translationId: string) =>
    api<{ translations: TranslationOut[] }>(
      `/api/vocabulary/items/${kind}/${id}/translations/${translationId}`,
      { method: 'DELETE' },
    ),
```

- [ ] **Step 2: useWordCard.ts**

In `saveTranslation`, replace `vocabularyApi.addTranslation('token' as ItemKind, ...)` with `vocabularyApi.addTranslation('token', ...)` and drop `is_primary: true` from the body. Add after `saveTranslation`:

```ts
  const updateTranslation = useMutation({
    mutationFn: (v: { itemId: string; translationId: string; text: string }) =>
      vocabularyApi.updateTranslation('token', v.itemId, v.translationId, v.text),
    onSuccess: invalidate,
  })

  const deleteTranslation = useMutation({
    mutationFn: (v: { itemId: string; translationId: string }) =>
      vocabularyApi.deleteTranslation('token', v.itemId, v.translationId),
    onSuccess: invalidate,
  })
```

Return them from the hook: `return { setStatus, saveTranslation, updateTranslation, deleteTranslation, saveNote, addTag, removeTag }`. Remove the now-unused `ItemKind` import if nothing else uses it.

- [ ] **Step 3: Verify compile + existing tests**

Run from `frontend/`: `corepack pnpm test -- --run src/features/reader/WordCard.test.tsx` and `corepack pnpm lint`
Expected: PASS (WordCard still calls addTranslation with a compatible body; the mocked module gains unused methods only). If the WordCard.test mock object lacks `updateTranslation`/`deleteTranslation`, add them to the `vi.mock` factory: `updateTranslation: vi.fn(), deleteTranslation: vi.fn(),`.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(FLQ-18): translation update/delete api methods" -- src/api/vocabulary.ts src/features/reader/useWordCard.ts src/features/reader/WordCard.test.tsx
```

---

### Task 5: TranslationFields component

**Files:**
- Create: `frontend/src/features/reader/TranslationFields.tsx`
- Test: `frontend/src/features/reader/TranslationFields.test.tsx`

**Interfaces:**
- Consumes: `TranslationOut` type from `@/api/vocabulary`.
- Produces (Task 6 relies on this exact contract):

```ts
interface TranslationFieldsProps {
  translations: TranslationOut[] // current target only, creation order (primary first)
  onCreate: (text: string) => Promise<void>
  onUpdate: (translationId: string, text: string) => Promise<void>
  onDelete: (translationId: string) => Promise<void>
}
export function TranslationFields(props: TranslationFieldsProps): JSX.Element
```

Behaviour (spec §2.1): one input per saved variant; Enter/blur saves (create/update/no-op); emptied field + Enter/blur deletes; hover reveals `+` (adds ONE pending empty field, focused) and `✕` (delete); zero variants → a single empty field always shown; save failure → inline «Не удалось сохранить», draft preserved, next Enter/blur retries.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/features/reader/TranslationFields.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { TranslationOut } from '@/api/vocabulary'
import { TranslationFields } from './TranslationFields'

const tr = (id: string, text: string, primary = false): TranslationOut => ({
  id, text, target_language_code: 'ru', is_primary: primary, source_type: 'user',
})

function setup(translations: TranslationOut[]) {
  const onCreate = vi.fn().mockResolvedValue(undefined)
  const onUpdate = vi.fn().mockResolvedValue(undefined)
  const onDelete = vi.fn().mockResolvedValue(undefined)
  render(
    <TranslationFields
      translations={translations}
      onCreate={onCreate}
      onUpdate={onUpdate}
      onDelete={onDelete}
    />,
  )
  return { onCreate, onUpdate, onDelete }
}

describe('TranslationFields', () => {
  it('shows a single empty field when there are no variants and creates on Enter', async () => {
    const { onCreate } = setup([])
    const input = screen.getByPlaceholderText('Введите новый перевод здесь')
    fireEvent.change(input, { target: { value: 'каждый' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith('каждый'))
  })

  it('renders one field per variant and updates an edited field on Enter', async () => {
    const { onUpdate } = setup([tr('T1', 'первый', true), tr('T2', 'второй')])
    const fields = screen.getAllByRole('textbox')
    expect(fields).toHaveLength(2)
    fireEvent.change(fields[1]!, { target: { value: 'второй!' } })
    fireEvent.keyDown(fields[1]!, { key: 'Enter' })
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith('T2', 'второй!'))
  })

  it('does not call anything when the value is unchanged on blur', async () => {
    const { onCreate, onUpdate, onDelete } = setup([tr('T1', 'первый', true)])
    fireEvent.blur(screen.getByDisplayValue('первый'))
    await new Promise((r) => setTimeout(r, 20))
    expect(onCreate).not.toHaveBeenCalled()
    expect(onUpdate).not.toHaveBeenCalled()
    expect(onDelete).not.toHaveBeenCalled()
  })

  it('deletes when a field is emptied and on ✕ click', async () => {
    const { onDelete } = setup([tr('T1', 'первый', true), tr('T2', 'второй')])
    const first = screen.getByDisplayValue('первый')
    fireEvent.change(first, { target: { value: '  ' } })
    fireEvent.keyDown(first, { key: 'Enter' })
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('T1'))
    fireEvent.click(screen.getByRole('button', { name: 'Удалить вариант: второй' }))
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('T2'))
  })

  it('adds a pending empty field via + and creates from it', async () => {
    const { onCreate } = setup([tr('T1', 'первый', true)])
    fireEvent.click(screen.getByRole('button', { name: 'Добавить вариант' }))
    const empty = screen.getByPlaceholderText('Введите новый перевод здесь')
    fireEvent.change(empty, { target: { value: 'новый' } })
    fireEvent.keyDown(empty, { key: 'Enter' })
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith('новый'))
  })

  it('keeps the draft and shows an inline error when saving fails, then retries', async () => {
    const onCreate = vi.fn().mockRejectedValueOnce(new Error('down')).mockResolvedValueOnce(undefined)
    render(
      <TranslationFields translations={[]} onCreate={onCreate}
        onUpdate={vi.fn()} onDelete={vi.fn()} />,
    )
    const input = screen.getByPlaceholderText('Введите новый перевод здесь')
    fireEvent.change(input, { target: { value: 'каждый' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await screen.findByText('Не удалось сохранить')
    expect((input as HTMLInputElement).value).toBe('каждый')
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(2))
    await waitFor(() =>
      expect(screen.queryByText('Не удалось сохранить')).not.toBeInTheDocument(),
    )
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `corepack pnpm test -- --run src/features/reader/TranslationFields.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the component**

Create `frontend/src/features/reader/TranslationFields.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Plus, X } from 'lucide-react'

import type { TranslationOut } from '@/api/vocabulary'

interface Props {
  /** Variants for the current target language, creation order (primary first). */
  translations: TranslationOut[]
  onCreate: (text: string) => Promise<void>
  onUpdate: (translationId: string, text: string) => Promise<void>
  onDelete: (translationId: string) => Promise<void>
}

/**
 * Translation variants as a list of inputs (spec §2.1): Enter/blur saves,
 * emptying a field deletes the variant, hover shows +/✕, a single empty
 * field is always present when there are no variants.
 */
export function TranslationFields({ translations, onCreate, onUpdate, onDelete }: Props) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  // null = no pending new field; '' or text = the single pending field's draft.
  const [newDraft, setNewDraft] = useState<string | null>(null)
  const [saveError, setSaveError] = useState(false)

  // Server list changed (save/delete landed): drop local drafts for rows that
  // now match, keep drafts the user is still editing elsewhere untouched.
  useEffect(() => {
    setDrafts({})
  }, [translations])

  const showAlwaysEmpty = translations.length === 0
  const pendingOpen = newDraft !== null || showAlwaysEmpty
  const pendingValue = newDraft ?? ''

  async function run(action: () => Promise<void>) {
    try {
      await action()
      setSaveError(false)
      return true
    } catch {
      setSaveError(true)
      return false
    }
  }

  async function commitExisting(t: TranslationOut) {
    const draft = drafts[t.id]
    if (draft === undefined) return
    const value = draft.trim()
    if (value === t.text) return
    if (value === '') {
      await run(() => onDelete(t.id))
      return
    }
    await run(() => onUpdate(t.id, value))
  }

  async function commitNew() {
    const value = pendingValue.trim()
    if (value === '') {
      if (!showAlwaysEmpty) setNewDraft(null)
      return
    }
    if (await run(() => onCreate(value))) setNewDraft(null)
  }

  function openNewField() {
    setNewDraft((v) => v ?? '')
  }

  return (
    <div data-testid="translation-fields" className="mt-1 space-y-2">
      {translations.map((t) => (
        <div key={t.id} className="group relative">
          <input
            className="w-full rounded-md border border-border px-3 py-2 pr-16 text-base"
            value={drafts[t.id] ?? t.text}
            onChange={(e) => setDrafts((d) => ({ ...d, [t.id]: e.target.value }))}
            onBlur={() => void commitExisting(t)}
            onKeyDown={(e) => { if (e.key === 'Enter') void commitExisting(t) }}
          />
          <span className="absolute inset-y-0 right-2 hidden items-center gap-1 group-focus-within:flex group-hover:flex">
            <button
              type="button" aria-label="Добавить вариант"
              onClick={openNewField}
              className="rounded p-1 text-muted-foreground hover:bg-accent"
            >
              <Plus className="h-4 w-4" />
            </button>
            <button
              type="button" aria-label={`Удалить вариант: ${t.text}`}
              onClick={() => void run(() => onDelete(t.id))}
              className="rounded p-1 text-muted-foreground hover:bg-accent"
            >
              <X className="h-4 w-4" />
            </button>
          </span>
        </div>
      ))}
      {pendingOpen && (
        <input
          // eslint-disable-next-line jsx-a11y/no-autofocus -- the field appears on explicit "+" click
          autoFocus={newDraft !== null}
          className="w-full rounded-md border border-border px-3 py-2 text-base"
          placeholder="Введите новый перевод здесь"
          value={pendingValue}
          onChange={(e) => setNewDraft(e.target.value)}
          onBlur={() => void commitNew()}
          onKeyDown={(e) => { if (e.key === 'Enter') void commitNew() }}
        />
      )}
      {saveError && <p className="text-sm text-destructive">Не удалось сохранить</p>}
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

Run: `corepack pnpm test -- --run src/features/reader/TranslationFields.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(FLQ-18): translation variant fields component" -- src/features/reader/TranslationFields.tsx src/features/reader/TranslationFields.test.tsx
```

---

### Task 6: WordCard integration — fields, suggestions, withItem helper

**Files:**
- Modify: `frontend/src/features/reader/WordCard.tsx`
- Test: `frontend/src/features/reader/WordCard.test.tsx`

**Interfaces:**
- Consumes: `TranslationFields` (Task 5), `updateTranslation`/`deleteTranslation` mutations (Task 4).
- Produces: WordCard without the single translation input and without the 800ms debounce; suggestions = AI + Wiktionary only under the «Подсказки» heading, `+` aria-label carries the source badge; a single `withItem` helper replaces the four `ensureItem`-then-mutate repeats. Note keeps blur-save (spec §2.1). Placeholder text stays `Введите новый перевод здесь` (it lives in TranslationFields now).

- [ ] **Step 1: Rewrite the translation-related tests**

In `WordCard.test.tsx`:
- Extend the `vi.mock('@/api/vocabulary')` factory with `updateTranslation: vi.fn(), deleteTranslation: vi.fn(),` (if not already done in Task 4).
- REWRITE `creates a tracked/0 item when a translation is typed on a new word`: replace `fireEvent.blur(input)` with `fireEvent.keyDown(input, { key: 'Enter' })` (Enter is now the primary gesture; blur also works but the test pins Enter).
- REWRITE `surfaces an inline error and retries...`: same replacement — `fireEvent.blur(input)` → `fireEvent.keyDown(input, { key: 'Enter' })` in both places.
- REWRITE `shows a Wiktionary suggestion and saves it as primary on +`: the button name becomes `Добавить перевод (📘): каждый`, and the assertion body drops `is_primary` (no longer sent):

```tsx
    const add = await screen.findByRole('button', { name: 'Добавить перевод (📘): каждый' })
    fireEvent.click(add)
    await waitFor(() => {
      expect(vocabularyApi.addTranslation).toHaveBeenCalledWith(
        'token', 'I1', expect.objectContaining({ translation_text: 'каждый', source_type: 'dictionary' }),
      )
    })
```

- ADD a test that saved variants render as fields and user translations are NOT in suggestions:

```tsx
  it('renders saved variants as fields and keeps them out of suggestions', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'tracked', confidence: 1,
      translations: {
        primary: { id: 'T1', text: 'первый', target_language_code: 'ru', is_primary: true, source_type: 'user' },
        all: [
          { id: 'T1', text: 'первый', target_language_code: 'ru', is_primary: true, source_type: 'user' },
          { id: 'T2', text: 'второй', target_language_code: 'ru', is_primary: false, source_type: 'user' },
        ],
      },
      note: null, tags: [],
    })
    renderCard()
    expect(await screen.findByDisplayValue('первый')).toBeInTheDocument()
    expect(await screen.findByDisplayValue('второй')).toBeInTheDocument()
    expect(screen.queryByText('Подсказки')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Добавить перевод .*: первый/ })).not.toBeInTheDocument()
  })
```

- ADD a delete-variant test:

```tsx
  it('deletes a variant via its ✕ button', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'tracked', confidence: 1,
      translations: {
        primary: { id: 'T1', text: 'первый', target_language_code: 'ru', is_primary: true, source_type: 'user' },
        all: [{ id: 'T1', text: 'первый', target_language_code: 'ru', is_primary: true, source_type: 'user' }],
      },
      note: null, tags: [],
    })
    vi.mocked(vocabularyApi.deleteTranslation).mockResolvedValue({ translations: [] })
    renderCard()
    const del = await screen.findByRole('button', { name: 'Удалить вариант: первый' })
    fireEvent.click(del)
    await waitFor(() => {
      expect(vocabularyApi.deleteTranslation).toHaveBeenCalledWith('token', 'I1', 'T1')
    })
  })
```

- The hotkeys-while-typing test stays as is (the empty field still renders with the same placeholder).

- [ ] **Step 2: Run tests to verify the new/changed ones fail**

Run: `corepack pnpm test -- --run src/features/reader/WordCard.test.tsx`
Expected: FAIL — WordCard still renders the single debounced input and old suggestion labels.

- [ ] **Step 3: Rework WordCard.tsx**

Changes, keeping everything not mentioned here as-is:

1. Imports: add `import { TranslationFields } from './TranslationFields'`; drop `useRef` pieces that die below.
2. DELETE: `draft`/`savedRef`/`dirtyRef` state, both draft-population effects, the 800ms debounce effect, and `saveTranslation()`.
3. Keep `saveError` only if still used by note saving — the note path keeps its inline «Не удалось сохранить»; translation errors now render inside `TranslationFields`.
4. Add the shared helper and use it in all four call sites (translation create, suggestion click, note save, tag add):

```tsx
  async function withItem(fn: (id: string) => Promise<unknown>): Promise<void> {
    const id = itemId ?? (await ensureItem('tracked', 0))
    await fn(id)
  }
```

  - note: `const prev = noteSavedRef.current; ... try { await withItem((id) => m.saveNote.mutateAsync({ itemId: id, note: value })); setSaveError(false) } catch { ... }` (structure unchanged, just via `withItem`).
  - tag add onKeyDown: `if (e.key === 'Enter' && tagDraft.trim()) { await withItem((id) => m.addTag.mutateAsync({ itemId: id, tag: tagDraft.trim() })); setTagDraft('') }`.
5. Variants for the current target — MUST be memoized: `TranslationFields`
   resets its per-field drafts when the `translations` prop identity changes,
   so a fresh `.filter()` array on every render would wipe the user's typing
   mid-edit:

```tsx
  const variants = useMemo(
    () => (data?.translations.all ?? []).filter((t) => t.target_language_code === target),
    [data, target],
  )
```

   (add `useMemo` to the react import).

6. Replace the single input block (label + input + saveError paragraph) with:

```tsx
        <label className="mt-4 block text-sm font-medium">Перевод</label>
        <TranslationFields
          translations={variants}
          onCreate={(value) => withItem((id) =>
            m.saveTranslation.mutateAsync({ itemId: id, text: value, source: 'user' }))}
          onUpdate={(translationId, value) => withItem((id) =>
            m.updateTranslation.mutateAsync({ itemId: id, translationId, text: value }))}
          onDelete={(translationId) => withItem((id) =>
            m.deleteTranslation.mutateAsync({ itemId: id, translationId }))}
        />
```

7. Suggestions: drop the user rows from the merged list; heading «Подсказки»; badge in the aria-label; collapsed cap of 2 (§4.1 — the cap uses the `expanded` flag that already exists):

```tsx
  type Suggestion = { text: string; badge: '✦' | '📘'; source: 'ai' | 'dictionary' }
  const suggestions: Suggestion[] = [
    ...(ai.data?.hints ?? []).map((h) => ({ text: h.text, badge: '✦' as const, source: 'ai' as const })),
    ...(dict.data?.entries ?? []).flatMap((e) =>
      e.senses.map((s) => ({ text: s.translation, badge: '📘' as const, source: 'dictionary' as const })),
    ),
  ]
  const visibleSuggestions = expanded ? suggestions : suggestions.slice(0, 2)
```

  Render `visibleSuggestions`; heading condition `visibleSuggestions.length > 0 && <p ...>Подсказки</p>`; `aria-label={`Добавить перевод (${sug.badge}): ${sug.text}`}`; `onClick={() => void withItem((id) => m.saveTranslation.mutateAsync({ itemId: id, text: sug.text, source: sug.source }))}` (delete the old `saveSuggestion`).
8. Enter-in-input hotkey note: the window `keydown` handler is unchanged (editable targets are already excluded).

- [ ] **Step 4: Run the full frontend suite**

Run: `corepack pnpm test`
Expected: PASS. If `SentenceView.test.tsx`/`ReaderPage.test.tsx` referenced the old placeholder or suggestion labels, update those references the same way.

- [ ] **Step 5: Lint and commit**

```bash
corepack pnpm lint
git commit -m "feat(FLQ-18): wordcard translation fields, suggestions without user rows" -- src/features/reader/WordCard.tsx src/features/reader/WordCard.test.tsx
```

---

### Task 7: Contextual AI + AI disabled/error states

**Files:**
- Modify: `frontend/src/features/reader/ReaderPage.tsx`
- Modify: `frontend/src/features/reader/WordCard.tsx`
- Test: `frontend/src/features/reader/WordCard.test.tsx`

**Interfaces:**
- Consumes: `ApiError` from `@/api/client` (already carries `status`), `isWord`/`Sentence` from `@/api/reader`.
- Produces: `WordCard` gains prop `sentenceText: string | null`; AI query uses `context_text = sentenceText ?? word.t`, its queryKey includes the context, and it is enabled for `new` AND `known` statuses (§3.1–3.2).

- [ ] **Step 1: Write failing tests**

In `WordCard.test.tsx`: `renderCard()` gains an optional param and passes it through:

```tsx
function renderCard(sentenceText: string | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <WordCard
        word={{ t: 'cada', n: 'cada', i: 0 }}
        lang="pt" target="ru" lessonId="L1" onClose={() => {}}
        sentenceText={sentenceText}
      />
    </QueryClientProvider>,
  )
}
```

REWRITE `does not call AI for a non-new word` (semantics changed): known now DOES call AI; tracked does not:

```tsx
  it('requests AI for known words but not for tracked ones', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'known', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    renderCard()
    await waitFor(() => expect(aiApi.translate).toHaveBeenCalled())

    vi.clearAllMocks()
    vi.mocked(dictionaryApi.lookup).mockResolvedValue({ entries: [], attribution: { source: '', license: '', url: '' }, external_links: [] })
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I2', status: 'tracked', confidence: 1,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    renderCard()
    await screen.findAllByText('cada')
    await new Promise((r) => setTimeout(r, 50))
    expect(aiApi.translate).not.toHaveBeenCalled()
  })
```

ADD:

```tsx
  it('passes the sentence as AI context when provided', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    renderCard('Cada casa tem uma porta.')
    await waitFor(() => {
      expect(aiApi.translate).toHaveBeenCalledWith(
        expect.objectContaining({ surface_text: 'cada', context_text: 'Cada casa tem uma porta.' }),
      )
    })
  })

  it('shows an info note without retry when AI is disabled (503)', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(aiApi.translate).mockRejectedValue(new ApiError(503, 'disabled'))
    renderCard()
    await screen.findByText('AI-переводы отключены')
    expect(screen.queryByText('Не удалось получить AI-перевод')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Повторить' })).not.toBeInTheDocument()
  })

  it('shows an inline error with retry on a real AI failure', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(aiApi.translate)
      .mockRejectedValueOnce(new ApiError(500, 'boom'))
      .mockResolvedValueOnce({ hints: [{ text: 'каждый' }], model: 'm', latency_ms: 1 })
    renderCard()
    await screen.findByText('Не удалось получить AI-перевод')
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    await screen.findByText(/каждый/)
  })
```

Add `import { ApiError } from '@/api/client'` to the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `corepack pnpm test -- --run src/features/reader/WordCard.test.tsx`
Expected: FAIL — no `sentenceText` prop, 503 renders as the generic error, no retry button, known doesn't query AI.

- [ ] **Step 3: WordCard changes**

- Props: add `sentenceText: string | null` to `Props` and destructure it.
- `import { ApiError } from '@/api/client'`.
- AI gate + query:

```tsx
  const wantAi = data?.status === 'new' || data?.status === 'known'
  const aiContext = sentenceText ?? word?.t ?? ''
  const ai = useQuery({
    queryKey: ['ai-hint', lang, target, text ?? '', aiContext],
    queryFn: () => aiApi.translate({
      surface_text: word!.t, context_text: aiContext,
      target_language_code: target, lesson_id: lessonId,
    }),
    enabled: text !== null && wantAi,
    retry: false,
  })
  const aiDisabled = ai.error instanceof ApiError && ai.error.status === 503
```

- Replace the `{ai.isError && <p ...>Не удалось получить AI-перевод</p>}` line with:

```tsx
          {aiDisabled && (
            <p className="mt-1 text-sm text-muted-foreground">AI-переводы отключены</p>
          )}
          {ai.isError && !aiDisabled && (
            <p className="mt-1 text-sm text-destructive">
              Не удалось получить AI-перевод{' '}
              <button
                type="button"
                onClick={() => void ai.refetch()}
                className="underline"
              >
                Повторить
              </button>
            </p>
          )}
```

- [ ] **Step 4: ReaderPage — derive and pass the sentence**

In `ReaderPage.tsx`, after the `flatSentences` memo:

```tsx
  const selectedSentenceText = useMemo(() => {
    if (!selectedWord) return null
    const sentence = flatSentences.find((s) =>
      s.tokens.some((tok) => isWord(tok) && tok.i === selectedWord.i),
    )
    return sentence?.text ?? null
  }, [selectedWord, flatSentences])
```

and pass `sentenceText={selectedSentenceText}` to `<WordCard ... />`.

- [ ] **Step 5: Run the full frontend suite**

Run: `corepack pnpm test`
Expected: PASS (fix any ReaderPage.test.tsx compile error by adding the prop where WordCard is not mocked).

- [ ] **Step 6: Lint and commit**

```bash
corepack pnpm lint
git commit -m "feat(FLQ-18): contextual AI hints, disabled info-note and retry" -- src/features/reader/WordCard.tsx src/features/reader/WordCard.test.tsx src/features/reader/ReaderPage.tsx
```

---

### Task 8: Layouts — ignored state, expand persistence, ReaderPage regression test

**Files:**
- Modify: `frontend/src/features/reader/WordCard.tsx`
- Modify: `frontend/src/features/reader/readerStore.ts`
- Test: `frontend/src/features/reader/WordCard.test.tsx`, `frontend/src/features/reader/ReaderPage.test.tsx`

**Interfaces:**
- Consumes: `useReaderStore` (Task adds `wordCardExpanded`).
- Produces: readerStore gains `wordCardExpanded: boolean` + `setWordCardExpanded(v: boolean)` — NOT persisted (stays out of `partialize`); WordCard `ignored` body per §4.2.

- [ ] **Step 1: Write failing tests**

In `WordCard.test.tsx` ADD:

```tsx
  it('shows the ignored layout with a reactivation hint and no editing blocks', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'ignored', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    renderCard()
    await screen.findByText('Игнорируется')
    expect(screen.getByText('Выберите уровень 1–4 или ✓, чтобы вернуть слово в изучение')).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Введите новый перевод здесь')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Развернуть' })).not.toBeInTheDocument()
    // footer stays for reactivation
    expect(screen.getByRole('button', { name: 'Уровень 1' })).toBeInTheDocument()
  })

  it('persists the expanded state across card reopen via the reader store', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'tracked', confidence: 1,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    const { unmount } = renderCard()
    fireEvent.click(await screen.findByRole('button', { name: 'Развернуть' }))
    await screen.findByText('Теги')
    unmount()
    renderCard()
    expect(await screen.findByText('Теги')).toBeInTheDocument()
    // restore the default for other tests
    fireEvent.click(screen.getByRole('button', { name: 'Свернуть' }))
  })
```

In `ReaderPage.test.tsx` ADD a regression test following that file's existing render/mocking pattern (reuse its helpers for content/status mocks; the point is the REAL WordCard renders on word click):

```tsx
  it('opens the real WordCard when a word is clicked', async () => {
    // arrange mocks exactly like the surrounding tests (ready lesson with content)
    // ... reuse the file's existing setup helper ...
    fireEvent.click(await screen.findByRole('button', { name: 'cada' }))
    expect(await screen.findByTestId('word-card')).toBeInTheDocument()
    expect(await screen.findByPlaceholderText('Введите новый перевод здесь')).toBeInTheDocument()
  })
```

(The implementer adapts the arrange block to the file's existing helpers — the two assertions are the requirement. If ReaderPage.test.tsx mocks `./WordCard`, remove that mock for this test file or scope the test to render the real one.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `corepack pnpm test -- --run src/features/reader/WordCard.test.tsx src/features/reader/ReaderPage.test.tsx`
Expected: FAIL — no ignored layout, expand resets on unmount, no such ReaderPage test.

- [ ] **Step 3: readerStore**

Add to `ReaderState` and the store body (NOT to `partialize`):

```ts
  wordCardExpanded: boolean
  setWordCardExpanded: (v: boolean) => void
```

```ts
      wordCardExpanded: false,
      setWordCardExpanded: (wordCardExpanded) => set({ wordCardExpanded }),
```

- [ ] **Step 4: WordCard**

- Replace `const [expanded, setExpanded] = useState(false)` with:

```tsx
  const expanded = useReaderStore((s) => s.wordCardExpanded)
  const setExpanded = useReaderStore((s) => s.setWordCardExpanded)
```

  (`import { useReaderStore } from './readerStore'`; the toggle button becomes `onClick={() => setExpanded(!expanded)}`.)
- Ignored layout: wrap the card body. When `status === 'ignored'` (and `data` is loaded), instead of the translation label/fields, suggestions block, expanded block and chevron, render:

```tsx
          <div data-testid="word-card-ignored" className="mt-4">
            <p className="text-sm font-medium">Игнорируется</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Выберите уровень 1–4 или ✓, чтобы вернуть слово в изучение
            </p>
          </div>
```

  The header (word + ✕) and the footer stay. Implementation shape: `const isIgnored = data?.status === 'ignored'`; conditionally render the normal body `{!isIgnored && (<>...translation label/fields, suggestions...</>)}`, `{expanded && !isIgnored && (...)}`, chevron button `{!isIgnored && (...)}`.

- [ ] **Step 5: Run the full frontend suite and lint**

Run: `corepack pnpm test && corepack pnpm lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(FLQ-18): ignored layout, persistent expand, reader wordcard test" -- src/features/reader/WordCard.tsx src/features/reader/WordCard.test.tsx src/features/reader/readerStore.ts src/features/reader/ReaderPage.test.tsx
```

---

### Task 9: Full verification pass

**Files:** none new — verification only.

- [ ] **Step 1: Backend full suite + gates**

From `backend/`: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pyright`
Expected: all green (format --check is the exact CI gate).

- [ ] **Step 2: Frontend full suite + gates**

From `frontend/`: `corepack pnpm test && corepack pnpm lint && corepack pnpm build`
Expected: all green.

- [ ] **Step 3: Manual smoke (dev stack)**

With postgres:5433/redis up: `uv run alembic upgrade head`, start `uv run flinq serve`, `uv run flinq worker`, `corepack pnpm dev`. In the reader: click a new word → type a translation → Enter → token turns blue (tracked/0); hover the field → `+`/`✕` appear; `+` → second variant; `✕` on the top field → primary moves; AI block shows «AI-переводы отключены» (LLM off); click `🗑` → ignored layout with the reactivation hint.
Expected: behaviours match spec §2.1, §3.2, §4.2.
