# Reader Phrase Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drag-выделение фразы (2–8 слов) в ридере → карточка фразы (AI-перевод, свой перевод, статус, заметки, теги) → подсветка сохранённых фраз во всех вхождениях с кликом.

**Architecture:** Бэкенд: новая таблица `phrase_items` (зеркало `token_items`), генерализация vocabulary-сервиса по `item_kind` (сателлиты уже полиморфные), лёгкий endpoint списка фраз. Фронтенд: матчинг вхождений на клиенте (leftmost-longest по слово-токенам), pointer-events автомат драга, рендер «ранов» токенов с обёрткой PhraseSpan, генерализация WordCard по kind.

**Tech Stack:** FastAPI + SQLAlchemy async + alembic + pytest; React + TypeScript + zustand + react-query + vitest.

**Spec:** `docs/superpowers/specs/2026-07-12-reader-phrase-selection-design.md`

## Global Constraints

- Языки: `en | ru | pt` (`LangCode` Literal во всех схемах).
- Фраза: **2–8 слово-токенов**; пунктуация входит в display-текст, но не в лимит и не в матчинг.
- `phrase_text` (join key) = нормализованные слово-токены через один пробел; нормализация ТОЛЬКО через `tokenize()` из `flinq/modules/lesson_library/tokenization.py` (гарантия совпадения с `n` токенов урока). `normalize_token`/`tokenize` — замороженный алгоритм, НЕ менять.
- Границы: фраза только внутри одного предложения (клампится на клиенте; бэкенд предложения не проверяет).
- Выделение: только мышь (`pointerType === 'mouse'`, ЛКМ).
- Матчинг вхождений: клиентский, только по слово-токенам, пересечения не поддерживаются (leftmost-longest). Подсвечиваются только `tracked`-фразы.
- Статусы/confidence: как у token_items (`tracked|known|ignored`, `tracked ⇔ confidence NOT NULL`, 0–5).
- Backend-команды из `backend/`: `uv run pytest <path> -v`, миграции `uv run alembic upgrade head`.
- Frontend-команды из `frontend/`: `corepack pnpm vitest run <path>`, типы `corepack pnpm tsc -b`, линт `corepack pnpm lint`.
- Коммиты: без Co-Authored-By трейлеров; `git add`/`git commit` только по явным путям.

---

### Task 1: `normalize_phrase`

**Files:**
- Modify: `backend/src/flinq/modules/lesson_library/tokenization.py` (после `tokenize`, ~строка 55)
- Test: `backend/tests/modules/lesson_library/test_normalize_phrase.py`

**Interfaces:**
- Consumes: `tokenize(text)` (существующий).
- Produces: `normalize_phrase(surface: str) -> str` — join key фразы; `""` если слов нет. Task 4 использует её в сервисе.

- [ ] **Step 1: Write the failing test**

```python
"""normalize_phrase: join key фразы (ADR-0001) поверх канонического tokenize."""

from flinq.modules.lesson_library.tokenization import normalize_phrase


def test_joins_normalized_words_with_single_space():
    assert normalize_phrase("So Far,  so GOOD") == "so far so good"


def test_punctuation_tokens_are_dropped():
    assert normalize_phrase("wait — really?!") == "wait really"


def test_internal_apostrophe_and_hyphen_kept():
    assert normalize_phrase("don’t give up") == "don't give up"  # noqa: RUF001
    assert normalize_phrase("a well-known fact") == "a well-known fact"


def test_empty_and_punct_only():
    assert normalize_phrase("") == ""
    assert normalize_phrase("?! …") == ""


def test_idempotent_on_normalized_text():
    assert normalize_phrase("so far so good") == "so far so good"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_normalize_phrase.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_phrase'`

- [ ] **Step 3: Write minimal implementation**

В `tokenization.py`, сразу после функции `tokenize`:

```python
def normalize_phrase(surface: str) -> str:
    """Phrase join key (ADR-0001): normalized word tokens joined by single spaces.

    Uses the same tokenizer as lesson import, so the result always matches the
    `normalized_text` sequence of lesson tokens. Punctuation tokens are dropped.
    """
    return " ".join(t.normalized_text for t in tokenize(surface) if t.is_word_like)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/modules/lesson_library/test_normalize_phrase.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/flinq/modules/lesson_library/tokenization.py backend/tests/modules/lesson_library/test_normalize_phrase.py
git commit -m "feat(vocab): normalize_phrase join key over canonical tokenizer"
```

---

### Task 2: `PhraseItem` model + migration

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/models.py` (после класса `TokenItem`)
- Create: `backend/migrations/versions/0010_phrase_items.py`
- Test: `backend/tests/modules/test_phrase_item_model.py`

**Interfaces:**
- Produces: класс `PhraseItem` с колонками `id, user_id, language_code, phrase_text, display_text, status, confidence, added_by, created_at, updated_at`. Tasks 3–7 используют его.

- [ ] **Step 1: Write the failing test**

```python
"""PhraseItem: roundtrip + DB constraints (уникальность, 2–8 слов)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo
from flinq.modules.vocabulary.models import PhraseItem


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
        await s.execute(delete(PhraseItem))


def _phrase(user_id: uuid.UUID, text: str = "so far so good") -> PhraseItem:
    return PhraseItem(
        user_id=user_id,
        language_code="en",
        phrase_text=text,
        display_text="So far, so good",
        status="tracked",
        confidence=1,
    )


async def test_roundtrip():
    async with session_scope() as s:
        user_id = await _make_user(s)
        s.add(_phrase(user_id))
        await s.flush()
        row = (await s.execute(select(PhraseItem))).scalar_one()
        assert row.phrase_text == "so far so good"
        assert row.added_by == "user"


async def test_unique_user_lang_text():
    async with session_scope() as s:
        user_id = await _make_user(s)
        s.add(_phrase(user_id))
        await s.flush()
        s.add(_phrase(user_id))
        with pytest.raises(IntegrityError):
            await s.flush()


async def test_word_count_check_rejects_single_word():
    async with session_scope() as s:
        user_id = await _make_user(s)
        s.add(_phrase(user_id, text="alone"))
        with pytest.raises(IntegrityError):
            await s.flush()


async def test_word_count_check_rejects_nine_words():
    async with session_scope() as s:
        user_id = await _make_user(s)
        s.add(_phrase(user_id, text="a b c d e f g h i"))
        with pytest.raises(IntegrityError):
            await s.flush()
```

- [ ] **Step 2: Write the model**

В `models.py`, после класса `TokenItem`:

```python
class PhraseItem(Base):
    """Saved multi-word phrase (ADR-0001: Phrase is a first-class entity).

    `phrase_text` is the normalized join key (normalize_phrase output —
    word tokens joined by single spaces); `display_text` is the raw surface
    slice including punctuation, for the card and vocabulary list.
    """

    __tablename__ = "phrase_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    language_code: Mapped[str] = mapped_column(String(8))
    phrase_text: Mapped[str] = mapped_column(Text)
    display_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # tracked | known | ignored
    confidence: Mapped[int | None] = mapped_column(Integer)
    added_by: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "language_code", "phrase_text", name="uq_phrase_items_user_lang_text"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 5)",
            name="ck_phrase_items_confidence_range",
        ),
        CheckConstraint(
            "(status = 'tracked') = (confidence IS NOT NULL)",
            name="ck_phrase_items_confidence_tracked",
        ),
        CheckConstraint("added_by IN ('user', 'bulk')", name="ck_phrase_items_added_by"),
        CheckConstraint(
            "array_length(string_to_array(phrase_text, ' '), 1) BETWEEN 2 AND 8",
            name="ck_phrase_items_word_count",
        ),
        Index("ix_phrase_items_user_lang", "user_id", "language_code"),
    )
```

- [ ] **Step 3: Write the migration**

`backend/migrations/versions/0010_phrase_items.py`:

```python
"""phrase items

Revision ID: 0010_phrase_items
Revises: 0009_item_provenance
Create Date: 2026-07-12 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_phrase_items"
down_revision: str | Sequence[str] | None = "0009_item_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phrase_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("language_code", sa.String(length=8), nullable=False),
        sa.Column("phrase_text", sa.Text(), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column(
            "added_by", sa.String(length=16), server_default="user", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "language_code", "phrase_text", name="uq_phrase_items_user_lang_text"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 5)",
            name="ck_phrase_items_confidence_range",
        ),
        sa.CheckConstraint(
            "(status = 'tracked') = (confidence IS NOT NULL)",
            name="ck_phrase_items_confidence_tracked",
        ),
        sa.CheckConstraint("added_by IN ('user', 'bulk')", name="ck_phrase_items_added_by"),
        sa.CheckConstraint(
            "array_length(string_to_array(phrase_text, ' '), 1) BETWEEN 2 AND 8",
            name="ck_phrase_items_word_count",
        ),
    )
    op.create_index("ix_phrase_items_user_lang", "phrase_items", ["user_id", "language_code"])


def downgrade() -> None:
    op.drop_index("ix_phrase_items_user_lang", table_name="phrase_items")
    op.drop_table("phrase_items")
```

- [ ] **Step 4: Apply migration and run tests**

Run: `cd backend && uv run alembic upgrade head && uv run pytest tests/modules/test_phrase_item_model.py -v`
Expected: миграция применяется; 4 теста PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/flinq/modules/vocabulary/models.py backend/migrations/versions/0010_phrase_items.py backend/tests/modules/test_phrase_item_model.py
git commit -m "feat(vocab): phrase_items table + model (migration 0010)"
```

---

### Task 3: Генерализация сателлитов сервиса по `kind`

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/service.py`
- Test: `backend/tests/modules/test_vocabulary_service_phrase.py`

**Interfaces:**
- Consumes: `PhraseItem` (Task 2).
- Produces: все публичные функции сервиса с параметром `kind` реально работают для `kind="phrase"` над сателлитами: `add_translation`, `update_translation`, `delete_translation`, `put_note`, `add_tag`, `remove_tag`. Внутренние: `_MODEL_BY_KIND`, `_owned_item(session, *, user_id, kind, item_id)`, `_item_translations(..., kind)`, `_list_tags(..., kind)`. Тип `VocabItem = TokenItem | PhraseItem`.

- [ ] **Step 1: Write the failing test**

```python
"""Сателлиты (translations/notes/tags) для kind='phrase' (FLQ phrase selection)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo
from flinq.modules.vocabulary import service
from flinq.modules.vocabulary.models import (
    ItemTag,
    PersonalNote,
    PersonalTranslation,
    PhraseItem,
    TokenItem,
)


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
        for model in (PersonalTranslation, PersonalNote, ItemTag, PhraseItem, TokenItem):
            await s.execute(delete(model))


async def _phrase_item(user_id: uuid.UUID) -> uuid.UUID:
    async with session_scope() as s:
        item = PhraseItem(
            user_id=user_id,
            language_code="en",
            phrase_text="so far so good",
            display_text="so far, so good",
            status="tracked",
            confidence=1,
        )
        s.add(item)
        await s.flush()
        return item.id


async def test_phrase_translation_roundtrip():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _phrase_item(user_id)
    async with session_scope() as s:
        row, created = await service.add_translation(
            s, user_id=user_id, kind="phrase", item_id=item_id,
            target_language_code="ru", translation_text="пока всё хорошо",
            source_type="user",
        )
        assert created and row.is_primary and row.item_kind == "phrase"
    async with session_scope() as s:
        updated = await service.update_translation(
            s, user_id=user_id, kind="phrase", item_id=item_id,
            translation_id=row.id, translation_text="пока что неплохо",
        )
        assert updated.translation_text == "пока что неплохо"
    async with session_scope() as s:
        remaining = await service.delete_translation(
            s, user_id=user_id, kind="phrase", item_id=item_id, translation_id=row.id
        )
        assert remaining == []


async def test_phrase_note_and_tags():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _phrase_item(user_id)
    async with session_scope() as s:
        note = await service.put_note(
            s, user_id=user_id, kind="phrase", item_id=item_id, note_text="идиома"
        )
        assert note.item_kind == "phrase"
    async with session_scope() as s:
        tags = await service.add_tag(
            s, user_id=user_id, kind="phrase", item_id=item_id, tag_name="idiom"
        )
        assert tags == ["idiom"]
    async with session_scope() as s:
        tags = await service.remove_tag(
            s, user_id=user_id, kind="phrase", item_id=item_id, tag_name="idiom"
        )
        assert tags == []


async def test_satellites_do_not_leak_across_kinds():
    """Токен и фраза с одинаковым item_id-скоупом не видят чужие сателлиты."""
    async with session_scope() as s:
        user_id = await _make_user(s)
        token = TokenItem(
            user_id=user_id, language_code="en", token_text="far",
            status="tracked", confidence=1,
        )
        s.add(token)
        await s.flush()
        token_id = token.id
    item_id = await _phrase_item(user_id)
    async with session_scope() as s:
        await service.add_tag(s, user_id=user_id, kind="phrase", item_id=item_id, tag_name="a")
    async with session_scope() as s:
        token_tags = await service._list_tags(  # noqa: SLF001 -- targeted internal check
            s, user_id=user_id, kind="token", item_id=token_id
        )
        assert token_tags == []


async def test_phrase_item_not_found_for_wrong_kind():
    async with session_scope() as s:
        user_id = await _make_user(s)
    item_id = await _phrase_item(user_id)
    async with session_scope() as s:
        with pytest.raises(service.ItemNotFound):
            await service.put_note(
                s, user_id=user_id, kind="token", item_id=item_id, note_text="x"
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_service_phrase.py -v`
Expected: FAIL — `UnsupportedKind: phrase`

- [ ] **Step 3: Refactor service.py**

3a. Импорт модели и реестр kind→model (заменить существующие `_check_kind`, `_promote_to_user`, `_owned_item`):

```python
from flinq.modules.vocabulary.models import (
    ItemTag,
    PersonalNote,
    PersonalTranslation,
    PhraseItem,
    TokenItem,
)

VocabItem = TokenItem | PhraseItem

_MODEL_BY_KIND: dict[str, type[TokenItem] | type[PhraseItem]] = {
    "token": TokenItem,
    "phrase": PhraseItem,
}


def _check_kind(kind: str) -> None:
    if kind not in _MODEL_BY_KIND:
        raise UnsupportedKind(kind)


def _promote_to_user(item: VocabItem) -> None:
    """Explicit user action on a bulk-created item claims it (spec FLQ-6.2 §1.2)."""
    if item.added_by != "user":
        item.added_by = "user"


async def _owned_item(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID
) -> VocabItem:
    item = await session.get(_MODEL_BY_KIND[kind], item_id)
    if item is None or item.user_id != user_id:
        raise ItemNotFound(str(item_id))
    return item
```

Docstring класса `UnsupportedKind` обнови: `"""Kind is not one of 'token' | 'phrase'."""`

3b. Прокинь `kind` в оба внутренних хелпера (сигнатура + фильтр):

```python
async def _list_tags(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID
) -> list[str]:
```
внутри: `ItemTag.item_kind == kind` (было `== "token"`).

```python
async def _item_translations(
    session: AsyncSession, *, user_id: uuid.UUID, kind: str, item_id: uuid.UUID
) -> list[PersonalTranslation]:
```
внутри: `PersonalTranslation.item_kind == kind`.

3c. Механические замены в телах публичных функций (в каждой уже есть параметр `kind`):

| Функция | Замены |
| --- | --- |
| `add_translation` | `_owned_item(..., kind=kind, ...)`; в `scope`: `item_kind == kind`; в `PersonalTranslation(...)`: `item_kind=kind`; возвратный `_item_translations` не вызывается |
| `update_translation` | `_owned_item(..., kind=kind, ...)`; duplicate-запрос: `item_kind == kind` |
| `delete_translation` | `_owned_item(..., kind=kind, ...)`; successor-запрос: `item_kind == kind`; финальный `_item_translations(..., kind=kind, ...)` |
| `put_note` | `_owned_item(..., kind=kind, ...)`; `values(..., item_kind=kind, ...)` |
| `add_tag` | `_owned_item(..., kind=kind, ...)`; `values(..., item_kind=kind, ...)`; `_list_tags(..., kind=kind, ...)` |
| `remove_tag` | `_owned_item(..., kind=kind, ...)`; `delete(...).where(ItemTag.item_kind == kind, ...)`; `_list_tags(..., kind=kind, ...)` |
| `patch_item` | `_owned_item(..., kind=kind, ...)` |
| `lookup` | вызовы `_item_translations(..., kind="token", ...)`, `_list_tags(..., kind="token", ...)`, note-запрос без изменений (`== "token"`) — phrase-ветка появится в Task 4 |

`_owned_translation` не меняется (владение проверяется по `item_id`, kind-скоуп дают вызывающие запросы).

- [ ] **Step 4: Run tests (новые + регресс)**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_service_phrase.py tests/modules/test_vocabulary_service.py tests/api/test_vocabulary.py -v`
Expected: все PASS (регресс токенов не сломан)

- [ ] **Step 5: Commit**

```bash
git add backend/src/flinq/modules/vocabulary/service.py backend/tests/modules/test_vocabulary_service_phrase.py
git commit -m "refactor(vocab): thread item kind through satellite service ops"
```

---

### Task 4: create/patch/lookup для фразы + API

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/service.py`
- Modify: `backend/src/flinq/modules/vocabulary/schemas.py`
- Modify: `backend/src/flinq/api/vocabulary.py`
- Test: `backend/tests/api/test_vocabulary_phrase.py`

**Interfaces:**
- Consumes: `normalize_phrase` (Task 1), `PhraseItem` (Task 2), kind-сателлиты (Task 3).
- Produces:
  - `service.InvalidPhrase(Exception)` — текст вне 2–8 слов.
  - `service.create_item(..., kind="phrase", text=<surface>)` → `PhraseItem` (upsert по `(user, lang, phrase_text)`; `display_text = text.strip()`).
  - `service.lookup(..., kind: str = "token")` — phrase-ветка.
  - API: `CreateItemRequest.kind: Literal["token","phrase"]`; `GET /lookup?kind=phrase`; все `/items/{kind}/...` роуты работают для phrase (удалён `_resolve`); `POST /items` с невалидной фразой → 422.

- [ ] **Step 1: Write the failing test**

```python
"""API: карточка фразы end-to-end (create/lookup/patch/translations)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from flinq.core.db import session_scope
from flinq.main import create_app
from flinq.modules.vocabulary.models import (
    ItemTag,
    PersonalNote,
    PersonalTranslation,
    PhraseItem,
    TokenItem,
)


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    async with session_scope() as s:
        for model in (PersonalTranslation, PersonalNote, ItemTag, PhraseItem, TokenItem):
            await s.execute(delete(model))


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def _register(c: AsyncClient) -> dict[str, str]:
    email = f"{uuid.uuid4().hex}@t.io"
    r = await c.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "display_name": "T"},
    )
    assert r.status_code == 201, r.text
    r = await c.post("/api/auth/login", json={"email": email, "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_lookup_unknown_phrase_returns_new():
    async with await _client() as c:
        h = await _register(c)
        r = await c.get(
            "/api/vocabulary/lookup",
            params={"lang": "en", "text": "so far, so good", "target": "ru", "kind": "phrase"},
            headers=h,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["item_id"] is None and body["status"] == "new"


async def test_create_phrase_then_lookup_normalizes():
    async with await _client() as c:
        h = await _register(c)
        r = await c.post(
            "/api/vocabulary/items",
            json={
                "kind": "phrase", "language_code": "en",
                "text": "So Far, so GOOD", "status": "tracked", "confidence": 1,
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
        item_id = r.json()["item_id"]
        # lookup по другому поверхностному варианту той же фразы
        r = await c.get(
            "/api/vocabulary/lookup",
            params={"lang": "en", "text": "so far so good", "target": "ru", "kind": "phrase"},
            headers=h,
        )
        assert r.json()["item_id"] == item_id
        assert r.json()["status"] == "tracked"


async def test_create_phrase_is_upsert():
    async with await _client() as c:
        h = await _register(c)
        body = {
            "kind": "phrase", "language_code": "en",
            "text": "give up", "status": "tracked", "confidence": 1,
        }
        r1 = await c.post("/api/vocabulary/items", json=body, headers=h)
        body["status"], body["confidence"] = "known", None
        r2 = await c.post("/api/vocabulary/items", json=body, headers=h)
        assert r1.json()["item_id"] == r2.json()["item_id"]
        assert r2.json()["status"] == "known"


async def test_create_phrase_rejects_one_and_nine_words():
    async with await _client() as c:
        h = await _register(c)
        for text in ("alone", "a b c d e f g h i"):
            r = await c.post(
                "/api/vocabulary/items",
                json={
                    "kind": "phrase", "language_code": "en",
                    "text": text, "status": "tracked", "confidence": 1,
                },
                headers=h,
            )
            assert r.status_code == 422, text


async def test_phrase_translations_and_patch():
    async with await _client() as c:
        h = await _register(c)
        r = await c.post(
            "/api/vocabulary/items",
            json={
                "kind": "phrase", "language_code": "en",
                "text": "give up", "status": "tracked", "confidence": 1,
            },
            headers=h,
        )
        item_id = r.json()["item_id"]
        r = await c.post(
            f"/api/vocabulary/items/phrase/{item_id}/translations",
            json={"target_language_code": "ru", "translation_text": "сдаться"},
            headers=h,
        )
        assert r.status_code == 201 and r.json()["is_primary"] is True
        r = await c.patch(
            f"/api/vocabulary/items/phrase/{item_id}",
            json={"status": "tracked", "confidence": 3},
            headers=h,
        )
        assert r.status_code == 200 and r.json()["confidence"] == 3
```

Примечание: `_register` скопируй из существующего `backend/tests/api/test_vocabulary.py`, если он отличается (auth-контракт мог измениться) — важно, чтобы регистрация/логин совпадали с текущими тестами.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_vocabulary_phrase.py -v`
Expected: FAIL (422/400 на kind=phrase)

- [ ] **Step 3: Service — phrase-ветки**

3a. Импорт + исключение (рядом с остальными исключениями):

```python
from flinq.modules.lesson_library.tokenization import normalize_phrase


class InvalidPhrase(Exception):  # noqa: N818 -- matches sibling exception naming
    """Phrase text has fewer than 2 or more than 8 word tokens."""
```

3b. Хелпер поиска фразы (рядом с `_get_token_item`):

```python
async def _get_phrase_item(
    session: AsyncSession, *, user_id: uuid.UUID, language_code: str, text: str
) -> PhraseItem | None:
    stmt = select(PhraseItem).where(
        PhraseItem.user_id == user_id,
        PhraseItem.language_code == language_code,
        PhraseItem.phrase_text == text,
    )
    return (await session.execute(stmt)).scalar_one_or_none()
```

3c. `create_item` — заменить целиком:

```python
async def create_item(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    language_code: str,
    text: str,
    status: str,
    confidence: int | None,
) -> VocabItem:
    _check_kind(kind)
    if kind == "phrase":
        normalized = normalize_phrase(text)
        word_count = len(normalized.split(" ")) if normalized else 0
        if not 2 <= word_count <= 8:
            raise InvalidPhrase(text)
        existing_phrase = await _get_phrase_item(
            session, user_id=user_id, language_code=language_code, text=normalized
        )
        if existing_phrase is not None:
            existing_phrase.status = status
            existing_phrase.confidence = confidence
            _promote_to_user(existing_phrase)
            await session.commit()
            return existing_phrase
        phrase = PhraseItem(
            user_id=user_id,
            language_code=language_code,
            phrase_text=normalized,
            display_text=text.strip(),
            status=status,
            confidence=confidence,
            added_by="user",
        )
        session.add(phrase)
        await session.commit()
        return phrase
    normalized = normalize_token(text)
    existing = await _get_token_item(
        session, user_id=user_id, language_code=language_code, text=normalized
    )
    if existing is not None:
        existing.status = status
        existing.confidence = confidence
        _promote_to_user(existing)
        await session.commit()
        return existing
    item = TokenItem(
        user_id=user_id,
        language_code=language_code,
        token_text=normalized,
        status=status,
        confidence=confidence,
        added_by="user",
    )
    session.add(item)
    await session.commit()
    return item
```

3d. `lookup` — добавить параметр и ветку выбора item (сателлитная часть уже общая):

```python
async def lookup(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    language_code: str,
    text: str,
    target_language_code: str,
    kind: str = "token",
) -> LookupResult:
    _check_kind(kind)
    if kind == "phrase":
        normalized = normalize_phrase(text)
        item: VocabItem | None = await _get_phrase_item(
            session, user_id=user_id, language_code=language_code, text=normalized
        )
    else:
        normalized = normalize_token(text)
        item = await _get_token_item(
            session, user_id=user_id, language_code=language_code, text=normalized
        )
    if item is None:
        return LookupResult(
            item_id=None, status="new", confidence=None,
            translations=[], primary=None, note=None, tags=[],
        )
    translations = await _item_translations(session, user_id=user_id, kind=kind, item_id=item.id)
    primary = next(
        (t for t in translations if t.is_primary and t.target_language_code == target_language_code),
        None,
    )
    note_row = (
        await session.execute(
            select(PersonalNote).where(
                PersonalNote.owner_user_id == user_id,
                PersonalNote.item_kind == kind,
                PersonalNote.item_id == item.id,
            )
        )
    ).scalar_one_or_none()
    tags = await _list_tags(session, user_id=user_id, kind=kind, item_id=item.id)
    return LookupResult(
        item_id=item.id, status=item.status, confidence=item.confidence,
        translations=translations, primary=primary,
        note=note_row.note_text if note_row else None, tags=tags,
    )
```

3e. `patch_item` возвращает `VocabItem` — поменяй аннотацию возврата с `TokenItem` на `VocabItem`.

- [ ] **Step 4: Schemas + API**

4a. `schemas.py`: в `CreateItemRequest` замени `kind: Literal["token"] = "token"` на `kind: Literal["token", "phrase"] = "token"`.

4b. `api/vocabulary.py`:
- Удали функцию `_resolve` и все 8 её вызовов (`_resolve(kind)` в patch_item, add_translation, update_translation, delete_translation, put_note, add_tag, remove_tag).
- `lookup`: добавь параметр `kind: Kind = "token"` и передай `kind=kind` в `service.lookup(...)`.
- `create_item`: оберни вызов сервиса:

```python
    try:
        item = await service.create_item(
            session,
            user_id=user_id,
            kind=body.kind,
            language_code=body.language_code,
            text=body.text,
            status=body.status,
            confidence=body.confidence,
        )
    except service.InvalidPhrase:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "phrase must contain 2..8 words"
        ) from None
```

- [ ] **Step 5: Run tests + regression + lint**

Run: `cd backend && uv run pytest tests/api/test_vocabulary_phrase.py tests/api/test_vocabulary.py tests/modules/ -v && uv run ruff check src tests`
Expected: все PASS, ruff чистый

- [ ] **Step 6: Commit**

```bash
git add backend/src/flinq/modules/vocabulary/service.py backend/src/flinq/modules/vocabulary/schemas.py backend/src/flinq/api/vocabulary.py backend/tests/api/test_vocabulary_phrase.py
git commit -m "feat(vocab): phrase create/lookup/patch through the item card API"
```

---

### Task 5: `GET /api/vocabulary/phrases`

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/service.py`
- Modify: `backend/src/flinq/modules/vocabulary/schemas.py`
- Modify: `backend/src/flinq/api/vocabulary.py`
- Test: `backend/tests/api/test_vocabulary_phrases_list.py`

**Interfaces:**
- Produces: `GET /api/vocabulary/phrases?lang=en` → `{"phrases": [{item_id, phrase_text, status, confidence}]}` (все фразы пользователя для языка, сортировка по created_at). Фронтенд (Task 8) читает этот контракт.

- [ ] **Step 1: Write the failing test**

```python
"""GET /api/vocabulary/phrases — лёгкий список для клиентского матчинга."""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from flinq.core.db import session_scope
from flinq.main import create_app
from flinq.modules.vocabulary.models import PhraseItem


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    yield
    async with session_scope() as s:
        await s.execute(delete(PhraseItem))


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


async def _register(c: AsyncClient) -> dict[str, str]:
    email = f"{uuid.uuid4().hex}@t.io"
    r = await c.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "display_name": "T"},
    )
    assert r.status_code == 201, r.text
    r = await c.post("/api/auth/login", json={"email": email, "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create_phrase(c: AsyncClient, h: dict[str, str], text: str, lang: str = "en") -> str:
    r = await c.post(
        "/api/vocabulary/items",
        json={
            "kind": "phrase", "language_code": lang,
            "text": text, "status": "tracked", "confidence": 1,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["item_id"]


async def test_lists_only_own_lang_phrases():
    async with await _client() as c:
        h = await _register(c)
        pid = await _create_phrase(c, h, "so far, so good")
        await _create_phrase(c, h, "тем не менее", lang="ru")
        r = await c.get("/api/vocabulary/phrases", params={"lang": "en"}, headers=h)
        assert r.status_code == 200
        phrases = r.json()["phrases"]
        assert [p["item_id"] for p in phrases] == [pid]
        assert phrases[0]["phrase_text"] == "so far so good"
        assert phrases[0]["status"] == "tracked"
        assert phrases[0]["confidence"] == 1


async def test_requires_auth():
    async with await _client() as c:
        r = await c.get("/api/vocabulary/phrases", params={"lang": "en"})
        assert r.status_code == 401


async def test_does_not_see_foreign_users_phrases():
    async with await _client() as c:
        h1 = await _register(c)
        await _create_phrase(c, h1, "give up")
        h2 = await _register(c)
        r = await c.get("/api/vocabulary/phrases", params={"lang": "en"}, headers=h2)
        assert r.json()["phrases"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_vocabulary_phrases_list.py -v`
Expected: FAIL — 404 (роута нет). Если 401-тест падает из-за валидации до auth — проверь порядок в остальных роутах (везде `_require_user` внутри тела) и повтори тот же паттерн.

- [ ] **Step 3: Implement**

`service.py` (в конец файла):

```python
async def list_phrases(
    session: AsyncSession, *, user_id: uuid.UUID, language_code: str
) -> list[PhraseItem]:
    return list(
        (
            await session.execute(
                select(PhraseItem)
                .where(
                    PhraseItem.user_id == user_id,
                    PhraseItem.language_code == language_code,
                )
                .order_by(PhraseItem.created_at, PhraseItem.id)
            )
        )
        .scalars()
        .all()
    )
```

`schemas.py` (после `TagsResponse`):

```python
class PhraseListEntryOut(BaseModel):
    item_id: uuid.UUID
    phrase_text: str
    status: ItemStatus
    confidence: int | None


class PhraseListResponse(BaseModel):
    phrases: list[PhraseListEntryOut]
```

`api/vocabulary.py` (перед `@router.get("", ...)`; импортируй новые схемы):

```python
@router.get("/phrases", response_model=PhraseListResponse)
async def list_phrases(
    request: Request,
    lang: LangCode,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PhraseListResponse:
    user_id = _require_user(request)
    rows = await service.list_phrases(session, user_id=user_id, language_code=lang)
    return PhraseListResponse(
        phrases=[
            PhraseListEntryOut(
                item_id=r.id,
                phrase_text=r.phrase_text,
                status=cast('Literal["tracked", "known", "ignored"]', r.status),
                confidence=r.confidence,
            )
            for r in rows
        ]
    )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/api/test_vocabulary_phrases_list.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/src/flinq/modules/vocabulary/service.py backend/src/flinq/modules/vocabulary/schemas.py backend/src/flinq/api/vocabulary.py backend/tests/api/test_vocabulary_phrases_list.py
git commit -m "feat(vocab): GET /api/vocabulary/phrases for reader-side matching"
```

---

### Task 6: Фразы в общем списке Vocabulary (union)

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/service.py` (`list_items`)
- Modify: `backend/src/flinq/modules/vocabulary/schemas.py` (`VocabListItemOut.kind`)
- Modify: `backend/src/flinq/api/vocabulary.py` (`list_vocabulary`)
- Test: `backend/tests/modules/test_vocabulary_list_phrase.py`

**Interfaces:**
- Consumes: `PhraseItem`.
- Produces: `service.list_items(..., kind: str)` принимает `"token" | "phrase" | "all"` и реально фильтрует; элементы фраз имеют `kind="phrase"`, `text=display_text`, `pos=None`, `context=None`. API `kind` расширяется до `Literal["token", "phrase", "all"]`.

- [ ] **Step 1: Write the failing test**

```python
"""list_items: union токенов и фраз (kind=token|phrase|all)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo
from flinq.modules.vocabulary import service
from flinq.modules.vocabulary.models import (
    ItemTag,
    PersonalNote,
    PersonalTranslation,
    PhraseItem,
    TokenItem,
)

LIST_DEFAULTS = dict(
    target_language_code="ru",
    statuses=["tracked", "known", "ignored"],
    confidence_min=None,
    confidence_max=None,
    tags=[],
    q=None,
    added_after=None,
    sort="created_at",
    sort_dir="desc",
    page=1,
    page_size=25,
    added_by="user",
)


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
        for model in (PersonalTranslation, PersonalNote, ItemTag, PhraseItem, TokenItem):
            await s.execute(delete(model))


async def _seed(user_id: uuid.UUID) -> None:
    async with session_scope() as s:
        s.add(TokenItem(
            user_id=user_id, language_code="en", token_text="far",
            status="tracked", confidence=1,
        ))
        s.add(PhraseItem(
            user_id=user_id, language_code="en",
            phrase_text="so far so good", display_text="so far, so good",
            status="tracked", confidence=2,
        ))


async def test_kind_all_returns_both():
    async with session_scope() as s:
        user_id = await _make_user(s)
    await _seed(user_id)
    async with session_scope() as s:
        items, total = await service.list_items(
            s, user_id=user_id, language_code="en", kind="all", **LIST_DEFAULTS
        )
        assert total == 2
        assert {(i.kind, i.text) for i in items} == {
            ("token", "far"), ("phrase", "so far, so good"),
        }
        phrase = next(i for i in items if i.kind == "phrase")
        assert phrase.pos is None and phrase.context is None


async def test_kind_filters():
    async with session_scope() as s:
        user_id = await _make_user(s)
    await _seed(user_id)
    async with session_scope() as s:
        items, total = await service.list_items(
            s, user_id=user_id, language_code="en", kind="phrase", **LIST_DEFAULTS
        )
        assert total == 1 and items[0].kind == "phrase"
        items, total = await service.list_items(
            s, user_id=user_id, language_code="en", kind="token", **LIST_DEFAULTS
        )
        assert total == 1 and items[0].kind == "token"


async def test_q_searches_phrase_display_text():
    async with session_scope() as s:
        user_id = await _make_user(s)
    await _seed(user_id)
    async with session_scope() as s:
        items, total = await service.list_items(
            s, user_id=user_id, language_code="en", kind="all",
            **{**LIST_DEFAULTS, "q": "so good"},
        )
        assert total == 1 and items[0].kind == "phrase"


async def test_phrase_primary_translation_hydrated():
    async with session_scope() as s:
        user_id = await _make_user(s)
    await _seed(user_id)
    async with session_scope() as s:
        phrase_id = (await s.execute(select(PhraseItem.id))).scalar_one()
        await service.add_translation(
            s, user_id=user_id, kind="phrase", item_id=phrase_id,
            target_language_code="ru", translation_text="пока всё хорошо",
            source_type="user",
        )
    async with session_scope() as s:
        items, _ = await service.list_items(
            s, user_id=user_id, language_code="en", kind="phrase", **LIST_DEFAULTS
        )
        assert items[0].primary_translation_text == "пока всё хорошо"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_list_phrase.py -v`
Expected: FAIL (фразы не возвращаются: `del kind`)

- [ ] **Step 3: Rewrite `list_items`**

Замени тело `list_items` целиком. Импорты сверху файла: добавь `literal, union_all` в импорт из `sqlalchemy`.

```python
def _branch_conditions(
    model: type[TokenItem] | type[PhraseItem],
    kind: str,
    *,
    user_id: uuid.UUID,
    language_code: str,
    target_language_code: str,
    statuses: list[str],
    confidence_min: int | None,
    confidence_max: int | None,
    tags: list[str],
    q: str | None,
    added_after: datetime | None,
    added_by: str,
) -> list[Any]:
    text_col = model.token_text if model is TokenItem else model.display_text
    conditions: list[Any] = [
        model.user_id == user_id,
        model.language_code == language_code,
        model.status.in_(statuses),
    ]
    if added_by == "user":
        conditions.append(model.added_by == "user")
    if confidence_min is not None or confidence_max is not None:
        conf: list[Any] = []
        if confidence_min is not None:
            conf.append(model.confidence >= confidence_min)
        if confidence_max is not None:
            conf.append(model.confidence <= confidence_max)
        # narrows only tracked rows; known/ignored pass (spec §3.1)
        conditions.append(or_(model.status != "tracked", and_(*conf)))
    for tag in tags:
        conditions.append(
            exists().where(
                ItemTag.owner_user_id == user_id,
                ItemTag.item_kind == kind,
                ItemTag.item_id == model.id,
                ItemTag.tag_name == tag,
            )
        )
    if q:
        pattern = f"%{q}%"
        conditions.append(
            or_(
                text_col.ilike(pattern),
                exists().where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == kind,
                    PersonalTranslation.item_id == model.id,
                    PersonalTranslation.target_language_code == target_language_code,
                    PersonalTranslation.is_primary.is_(True),
                    PersonalTranslation.translation_text.ilike(pattern),
                ),
            )
        )
    if added_after is not None:
        conditions.append(model.created_at >= added_after)
    return conditions


def _branch_select(model: type[TokenItem] | type[PhraseItem], kind: str, conditions: list[Any]):  # noqa: ANN201 -- SQLAlchemy Select generics not worth spelling
    text_col = model.token_text if model is TokenItem else model.display_text
    return select(
        model.id.label("id"),
        literal(kind).label("kind"),
        text_col.label("text"),
        model.status.label("status"),
        model.confidence.label("confidence"),
        model.created_at.label("created_at"),
    ).where(*conditions)
```

Новое тело `list_items` (сигнатура прежняя, docstring обнови — kind теперь работает):

```python
    common = dict(
        user_id=user_id,
        language_code=language_code,
        target_language_code=target_language_code,
        statuses=statuses,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        tags=tags,
        q=q,
        added_after=added_after,
        added_by=added_by,
    )
    branches = []
    if kind in ("token", "all"):
        branches.append(_branch_select(TokenItem, "token", _branch_conditions(TokenItem, "token", **common)))
    if kind in ("phrase", "all"):
        branches.append(_branch_select(PhraseItem, "phrase", _branch_conditions(PhraseItem, "phrase", **common)))
    base = branches[0] if len(branches) == 1 else union_all(*branches)
    sub = base.subquery()

    total = (
        await session.execute(select(func.count()).select_from(sub))
    ).scalar_one()

    order_col = sub.c.text if sort == "text" else sub.c.created_at
    order_by = order_col.asc() if sort_dir == "asc" else order_col.desc()
    rows = (
        await session.execute(
            select(sub).order_by(order_by, sub.c.id).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    if not rows:
        return [], total

    ids_by_kind: dict[str, list[uuid.UUID]] = {}
    for r in rows:
        ids_by_kind.setdefault(r.kind, []).append(r.id)

    primary_map: dict[tuple[str, uuid.UUID], PersonalTranslation] = {}
    tags_map: dict[tuple[str, uuid.UUID], list[str]] = {}
    for row_kind, ids in ids_by_kind.items():
        for t in (
            await session.execute(
                select(PersonalTranslation).where(
                    PersonalTranslation.owner_user_id == user_id,
                    PersonalTranslation.item_kind == row_kind,
                    PersonalTranslation.item_id.in_(ids),
                    PersonalTranslation.target_language_code == target_language_code,
                    PersonalTranslation.is_primary.is_(True),
                )
            )
        ).scalars():
            primary_map[(row_kind, t.item_id)] = t
        for item_id, tag_name in (
            await session.execute(
                select(ItemTag.item_id, ItemTag.tag_name)
                .where(
                    ItemTag.owner_user_id == user_id,
                    ItemTag.item_kind == row_kind,
                    ItemTag.item_id.in_(ids),
                )
                .order_by(ItemTag.tag_name)
            )
        ).all():
            tags_map.setdefault((row_kind, item_id), []).append(tag_name)
```

Дальше — существующие `pos_map`/`context_map` запросы, но `texts` считай только по токен-строкам: `texts = [r.text for r in rows if r.kind == "token"]`; оба запроса выполняй только `if texts:` (иначе пустые dict). Финальная сборка:

```python
    result: list[VocabListItem] = []
    for r in rows:
        primary = primary_map.get((r.kind, r.id))
        is_token = r.kind == "token"
        result.append(
            VocabListItem(
                item_id=r.id,
                kind=r.kind,
                text=r.text,
                status=r.status,
                confidence=r.confidence,
                primary_translation_text=primary.translation_text if primary else None,
                primary_translation_target=(primary.target_language_code if primary else None),
                tags=tags_map.get((r.kind, r.id), []),
                pos=pos_map.get(r.text) if is_token else None,
                context=context_map.get(r.text) if is_token else None,
                created_at=r.created_at,
            )
        )
    return result, total
```

- [ ] **Step 4: Schemas + API**

- `schemas.py`: `VocabListItemOut.kind: Literal["token"]` → `Literal["token", "phrase"]`.
- `api/vocabulary.py` `list_vocabulary`: параметр `kind: Literal["token", "all"] = "all"` → `kind: Literal["token", "phrase", "all"] = "all"`; в сборке ответа `kind="token"` → `kind=cast('Literal["token", "phrase"]', i.kind)`.

- [ ] **Step 5: Run tests + regression**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_list_phrase.py tests/modules/test_vocabulary_list.py tests/api/test_vocabulary_page.py -v`
Expected: все PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/flinq/modules/vocabulary/service.py backend/src/flinq/modules/vocabulary/schemas.py backend/src/flinq/api/vocabulary.py backend/tests/modules/test_vocabulary_list_phrase.py
git commit -m "feat(vocab): phrases in the vocabulary list (token+phrase union)"
```

---

### Task 7: bulk-операции по обоим kind

**Files:**
- Modify: `backend/src/flinq/modules/vocabulary/service.py` (`bulk_action`)
- Test: `backend/tests/modules/test_vocabulary_bulk_phrase.py`

**Interfaces:**
- Produces: `bulk_action` применяет set_known/set_ignored/delete/add_tag к phrase-item id так же, как к token-item id (id обеих таблиц в одном списке).

- [ ] **Step 1: Write the failing test**

```python
"""bulk_action покрывает phrase_items."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import session_scope
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo
from flinq.modules.vocabulary import service
from flinq.modules.vocabulary.models import (
    ItemTag,
    PersonalNote,
    PersonalTranslation,
    PhraseItem,
    TokenItem,
)


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
        for model in (PersonalTranslation, PersonalNote, ItemTag, PhraseItem, TokenItem):
            await s.execute(delete(model))


async def _seed(user_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    async with session_scope() as s:
        token = TokenItem(
            user_id=user_id, language_code="en", token_text="far",
            status="tracked", confidence=1,
        )
        phrase = PhraseItem(
            user_id=user_id, language_code="en",
            phrase_text="so far so good", display_text="so far, so good",
            status="tracked", confidence=1,
        )
        s.add_all([token, phrase])
        await s.flush()
        return token.id, phrase.id


async def test_set_known_covers_both_kinds():
    async with session_scope() as s:
        user_id = await _make_user(s)
    token_id, phrase_id = await _seed(user_id)
    async with session_scope() as s:
        affected = await service.bulk_action(
            s, user_id=user_id, item_ids=[token_id, phrase_id],
            action="set_known", tag_name=None,
        )
        assert affected == 2
    async with session_scope() as s:
        phrase = await s.get(PhraseItem, phrase_id)
        assert phrase is not None and phrase.status == "known" and phrase.confidence is None


async def test_delete_phrase_removes_satellites():
    async with session_scope() as s:
        user_id = await _make_user(s)
    _, phrase_id = await _seed(user_id)
    async with session_scope() as s:
        await service.add_tag(s, user_id=user_id, kind="phrase", item_id=phrase_id, tag_name="x")
    async with session_scope() as s:
        affected = await service.bulk_action(
            s, user_id=user_id, item_ids=[phrase_id], action="delete", tag_name=None
        )
        assert affected == 1
    async with session_scope() as s:
        assert await s.get(PhraseItem, phrase_id) is None
        tags = (await s.execute(select(ItemTag))).scalars().all()
        assert tags == []


async def test_add_tag_covers_phrase():
    async with session_scope() as s:
        user_id = await _make_user(s)
    _, phrase_id = await _seed(user_id)
    async with session_scope() as s:
        affected = await service.bulk_action(
            s, user_id=user_id, item_ids=[phrase_id], action="add_tag", tag_name="idiom"
        )
        assert affected == 1
    async with session_scope() as s:
        tag = (await s.execute(select(ItemTag))).scalar_one()
        assert tag.item_kind == "phrase" and tag.tag_name == "idiom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/modules/test_vocabulary_bulk_phrase.py -v`
Expected: FAIL (affected считает только токены)

- [ ] **Step 3: Rewrite `bulk_action`**

```python
async def bulk_action(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    action: str,
    tag_name: str | None,
) -> int:
    """Bulk operation over the caller's token AND phrase items (spec §3.2).

    Unknown/foreign ids are silently skipped. One transaction.
    """
    owned_by_kind: dict[str, list[uuid.UUID]] = {}
    for kind, model in _MODEL_BY_KIND.items():
        ids = (
            (
                await session.execute(
                    select(model.id).where(model.user_id == user_id, model.id.in_(item_ids))
                )
            )
            .scalars()
            .all()
        )
        if ids:
            owned_by_kind[kind] = list(ids)
    if not owned_by_kind:
        return 0

    if action in ("set_known", "set_ignored"):
        new_status = "known" if action == "set_known" else "ignored"
        for kind, ids in owned_by_kind.items():
            model = _MODEL_BY_KIND[kind]
            await session.execute(
                update(model)
                .where(model.id.in_(ids))
                .values(status=new_status, confidence=None, added_by="user")
            )
    elif action == "delete":
        for kind, ids in owned_by_kind.items():
            for satellite in (PersonalTranslation, PersonalNote, ItemTag):
                await session.execute(
                    delete(satellite).where(
                        satellite.owner_user_id == user_id,
                        satellite.item_kind == kind,
                        satellite.item_id.in_(ids),
                    )
                )
            model = _MODEL_BY_KIND[kind]
            await session.execute(delete(model).where(model.id.in_(ids)))
    elif action == "add_tag":
        assert tag_name is not None  # validated at the API layer
        for kind, ids in owned_by_kind.items():
            model = _MODEL_BY_KIND[kind]
            await session.execute(update(model).where(model.id.in_(ids)).values(added_by="user"))
            for item_id in ids:
                await session.execute(
                    pg_insert(ItemTag)
                    .values(
                        id=uuid.uuid4(),
                        owner_user_id=user_id,
                        item_kind=kind,
                        item_id=item_id,
                        tag_name=tag_name,
                    )
                    .on_conflict_do_nothing(constraint="uq_item_tags")
                )
    await session.commit()
    return sum(len(ids) for ids in owned_by_kind.values())
```

- [ ] **Step 4: Run tests + regression + full backend suite**

Run: `cd backend && uv run pytest tests/ -v --timeout=120 -q && uv run ruff check src tests`
Expected: весь backend-набор PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/flinq/modules/vocabulary/service.py backend/tests/modules/test_vocabulary_bulk_phrase.py
git commit -m "feat(vocab): bulk actions over token and phrase items"
```

---

### Task 8: Фронтенд API-слой

**Files:**
- Modify: `frontend/src/api/vocabulary.ts`

**Interfaces:**
- Consumes: контракты Task 4–6.
- Produces (Tasks 9, 13, 14 используют):
  - `vocabularyApi.lookup(lang, text, target, kind: ItemKind = 'token')`
  - `vocabularyApi.phrases(lang) => Promise<PhraseListEntry[]>`
  - `vocabularyApi.createItem` с `kind: ItemKind`
  - `interface PhraseListEntry { item_id: string; phrase_text: string; status: 'tracked'|'known'|'ignored'; confidence: number|null }`
  - `VocabListItem.kind: 'token' | 'phrase'`; `VocabListParams.kind?: 'token' | 'phrase' | 'all'`

- [ ] **Step 1: Apply the edits**

В `frontend/src/api/vocabulary.ts`:

```ts
// VocabListItem: kind: 'token'  ->  kind: 'token' | 'phrase'
// VocabListParams: kind?: 'token' | 'all'  ->  kind?: 'token' | 'phrase' | 'all'

export interface PhraseListEntry {
  item_id: string
  phrase_text: string
  status: 'tracked' | 'known' | 'ignored'
  confidence: number | null
}
```

`lookup` и `createItem`:

```ts
  lookup: (lang: string, text: string, target: string, kind: ItemKind = 'token') => {
    const q = new URLSearchParams({ lang, text, target, kind })
    return api<WordLookup>(`/api/vocabulary/lookup?${q.toString()}`)
  },
  createItem: (body: {
    kind: ItemKind; language_code: string; text: string
    status: WriteStatus; confidence: number | null
  }) => api<ItemState>('/api/vocabulary/items', { method: 'POST', body: JSON.stringify(body) }),
```

Новый метод (после `lookup`):

```ts
  phrases: (lang: string) => {
    const q = new URLSearchParams({ lang })
    return api<{ phrases: PhraseListEntry[] }>(`/api/vocabulary/phrases?${q.toString()}`).then(
      (r) => r.phrases,
    )
  },
```

- [ ] **Step 2: Typecheck + existing tests**

Run: `cd frontend && corepack pnpm tsc -b && corepack pnpm vitest run src/features/vocabulary`
Expected: типы чистые, тесты Vocabulary PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/vocabulary.ts
git commit -m "feat(api): phrase kind + phrases list in vocabulary client"
```

---

### Task 9: `phraseMatching.ts`

**Files:**
- Create: `frontend/src/features/reader/phraseMatching.ts`
- Test: `frontend/src/features/reader/phraseMatching.test.ts`

**Interfaces:**
- Consumes: `Token`, `Sentence`, `isWord` из `@/api/reader`; `PhraseListEntry` (Task 8).
- Produces (Tasks 12, 14):
  - `buildPhraseIndex(entries: PhraseListEntry[]): PhraseIndex` — только `tracked`-фразы.
  - `matchPhrases(tokens: Token[], index: PhraseIndex): PhraseMatch[]` — `{ startIdx, endIdx, entry }`, индексы массива токенов, leftmost-longest, без пересечений.
  - `buildSelection(sentence: Sentence, fromOrdinal: number, toOrdinal: number): PhraseSelection | null` — `{ text, displayText, firstOrdinal }`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'

import type { Token } from '@/api/reader'
import type { PhraseListEntry } from '@/api/vocabulary'

import { buildPhraseIndex, buildSelection, matchPhrases } from './phraseMatching'

const ws: Token = { ws: ' ' }
const w = (t: string, i: number, n = t.toLowerCase()): Token => ({ t, n, i })
const p = (s: string): Token => ({ p: s })

const entry = (
  id: string,
  phrase_text: string,
  status: PhraseListEntry['status'] = 'tracked',
): PhraseListEntry => ({ item_id: id, phrase_text, status, confidence: 1 })

// "So far , so good it is"
const tokens: Token[] = [
  w('So', 10), ws, w('far', 11), p(','), ws, w('so', 12), ws, w('good', 13),
  ws, w('it', 14), ws, w('is', 15),
]

describe('buildPhraseIndex', () => {
  it('indexes tracked phrases by first word, longest first', () => {
    const idx = buildPhraseIndex([entry('a', 'so far'), entry('b', 'so far so good')])
    const list = idx.get('so')!
    expect(list.map((e) => e.itemId)).toEqual(['b', 'a'])
  })

  it('skips known/ignored phrases', () => {
    const idx = buildPhraseIndex([entry('a', 'so far', 'known')])
    expect(idx.size).toBe(0)
  })
})

describe('matchPhrases', () => {
  it('matches across punctuation (leftmost-longest)', () => {
    const idx = buildPhraseIndex([entry('a', 'so far'), entry('b', 'so far so good')])
    const matches = matchPhrases(tokens, idx)
    expect(matches).toHaveLength(1)
    expect(matches[0]).toMatchObject({ startIdx: 0, endIdx: 7 })
    expect(matches[0].entry.itemId).toBe('b')
  })

  it('non-overlapping: next scan starts after previous match', () => {
    const idx = buildPhraseIndex([entry('a', 'so good'), entry('b', 'good it')])
    const matches = matchPhrases(tokens, idx)
    expect(matches).toHaveLength(1)
    expect(matches[0].entry.itemId).toBe('a')
  })

  it('no match when a word differs', () => {
    const idx = buildPhraseIndex([entry('a', 'so bad')])
    expect(matchPhrases(tokens, idx)).toHaveLength(0)
  })

  it("matches phrases containing don't as one word", () => {
    const toks: Token[] = [w("Don't", 0, "don't"), ws, w('stop', 1)]
    const idx = buildPhraseIndex([entry('a', "don't stop")])
    expect(matchPhrases(toks, idx)).toHaveLength(1)
  })
})

describe('buildSelection', () => {
  const sentence = {
    seg_id: 's1', index: 0, text: 'So far, so good it is',
    normalized_text: 'so far so good it is', tokens,
  }

  it('builds normalized and display text over the ordinal range', () => {
    const sel = buildSelection(sentence, 10, 13)
    expect(sel).toEqual({
      text: 'so far so good',
      displayText: 'So far, so good',
      firstOrdinal: 10,
    })
  })

  it('returns null for a single word', () => {
    expect(buildSelection(sentence, 12, 12)).toBeNull()
  })

  it('returns null when range has no words', () => {
    expect(buildSelection(sentence, 90, 99)).toBeNull()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && corepack pnpm vitest run src/features/reader/phraseMatching.test.ts`
Expected: FAIL — модуля нет

- [ ] **Step 3: Implement**

```ts
import { isWord, type Sentence, type Token } from '@/api/reader'
import type { PhraseListEntry } from '@/api/vocabulary'

export interface PhraseEntry {
  itemId: string
  words: string[]
  status: 'tracked' | 'known' | 'ignored'
  confidence: number | null
}

/** Первое слово фразы -> кандидаты по убыванию длины (leftmost-longest). */
export type PhraseIndex = Map<string, PhraseEntry[]>

/** Индексируются только tracked-фразы: known/ignored не подсвечиваем (как слова). */
export function buildPhraseIndex(entries: PhraseListEntry[]): PhraseIndex {
  const index: PhraseIndex = new Map()
  for (const e of entries) {
    if (e.status !== 'tracked') continue
    const words = e.phrase_text.split(' ')
    if (words.length < 2) continue
    const list = index.get(words[0]) ?? []
    list.push({ itemId: e.item_id, words, status: e.status, confidence: e.confidence })
    index.set(words[0], list)
  }
  for (const list of index.values()) list.sort((a, b) => b.words.length - a.words.length)
  return index
}

export interface PhraseMatch {
  /** Индекс в массиве токенов предложения (первый слово-токен фразы). */
  startIdx: number
  /** Индекс последнего слово-токена фразы, включительно. */
  endIdx: number
  entry: PhraseEntry
}

function tryMatch(tokens: Token[], startIdx: number, words: string[]): number | null {
  let wi = 0
  let last = startIdx
  for (let ti = startIdx; ti < tokens.length && wi < words.length; ti++) {
    const tok = tokens[ti]
    if (!isWord(tok)) continue
    if (tok.n !== words[wi]) return null
    last = ti
    wi++
  }
  return wi === words.length ? last : null
}

/** Пунктуация/пробелы прозрачны; пересечения не поддерживаются. */
export function matchPhrases(tokens: Token[], index: PhraseIndex): PhraseMatch[] {
  const matches: PhraseMatch[] = []
  let i = 0
  while (i < tokens.length) {
    const tok = tokens[i]
    if (!isWord(tok)) {
      i++
      continue
    }
    const candidates = index.get(tok.n)
    let matched: PhraseMatch | null = null
    if (candidates) {
      for (const entry of candidates) {
        const end = tryMatch(tokens, i, entry.words)
        if (end !== null) {
          matched = { startIdx: i, endIdx: end, entry }
          break
        }
      }
    }
    if (matched) {
      matches.push(matched)
      i = matched.endIdx + 1
    } else {
      i++
    }
  }
  return matches
}

export interface PhraseSelection {
  /** Нормализованный join key (слова через пробел). */
  text: string
  /** Поверхностный срез с пунктуацией, обрезанный по краям. */
  displayText: string
  firstOrdinal: number
}

export function buildSelection(
  sentence: Sentence,
  fromOrdinal: number,
  toOrdinal: number,
): PhraseSelection | null {
  const words = sentence.tokens
    .map((tok, idx) => ({ tok, idx }))
    .filter(
      (x): x is { tok: WordToken; idx: number } =>
        isWord(x.tok) && x.tok.i >= fromOrdinal && x.tok.i <= toOrdinal,
    )
  if (words.length < 2) return null
  const startIdx = words[0].idx
  const endIdx = words[words.length - 1].idx
  const displayText = sentence.tokens
    .slice(startIdx, endIdx + 1)
    .map((t) => ('t' in t ? t.t : 'p' in t ? t.p : t.ws))
    .join('')
    .trim()
  const text = words.map((x) => x.tok.n).join(' ')
  return { text, displayText, firstOrdinal: words[0].tok.i }
}
```

(`WordToken` добавь в именованный импорт из `@/api/reader` рядом с `Sentence`/`Token`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && corepack pnpm vitest run src/features/reader/phraseMatching.test.ts && corepack pnpm tsc -b`
Expected: PASS, типы чистые

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/reader/phraseMatching.ts frontend/src/features/reader/phraseMatching.test.ts
git commit -m "feat(reader): client-side phrase occurrence matching (leftmost-longest)"
```

---

### Task 10: `usePhraseSelection`

**Files:**
- Create: `frontend/src/features/reader/usePhraseSelection.ts`
- Test: `frontend/src/features/reader/usePhraseSelection.test.tsx`

**Interfaces:**
- Consumes: `Sentence`, `isWord`.
- Produces (Task 14):

```ts
export interface DragRange { from: number; to: number } // word ordinals, inclusive
export const MAX_PHRASE_WORDS = 8
export function usePhraseSelection(params: {
  enabled: boolean
  sentences: Sentence[]
  onSelect: (range: DragRange, sentence: Sentence) => void
}): {
  dragRange: DragRange | null
  containerProps: {
    onPointerDown: React.PointerEventHandler
    onPointerOver: React.PointerEventHandler
    onPointerUp: React.PointerEventHandler
    onPointerCancel: React.PointerEventHandler
    onMouseDown: React.MouseEventHandler
    onClickCapture: React.MouseEventHandler
    style?: React.CSSProperties
  }
}
```

- [ ] **Step 1: Write the failing test**

Тест через маленький harness-компонент (jsdom не делает hit-testing — обходимся `fireEvent` с `target` на спанах):

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Sentence, Token } from '@/api/reader'

import { MAX_PHRASE_WORDS, usePhraseSelection, type DragRange } from './usePhraseSelection'

const w = (t: string, i: number): Token => ({ t, n: t.toLowerCase(), i })
const ws: Token = { ws: ' ' }

function sentence(seg: string, words: string[], firstOrdinal: number): Sentence {
  const tokens: Token[] = []
  words.forEach((word, k) => {
    if (k > 0) tokens.push(ws)
    tokens.push(w(word, firstOrdinal + k))
  })
  return {
    seg_id: seg, index: 0, text: words.join(' '),
    normalized_text: words.join(' ').toLowerCase(), tokens,
  }
}

const s1 = sentence('s1', ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'], 0)
const s2 = sentence('s2', ['other', 'words'], 10)

function Harness({ onSelect }: { onSelect: (r: DragRange, s: Sentence) => void }) {
  const { dragRange, containerProps } = usePhraseSelection({
    enabled: true,
    sentences: [s1, s2],
    onSelect,
  })
  return (
    <div data-testid="container" {...containerProps}>
      <span data-testid="drag-range">{dragRange ? `${dragRange.from}-${dragRange.to}` : ''}</span>
      {[s1, s2].flatMap((s) =>
        s.tokens.map((tok, i) =>
          't' in tok ? (
            <span key={`${s.seg_id}-${i}`} data-ordinal={tok.i} data-testid={`w-${tok.i}`}>
              {tok.t}
            </span>
          ) : (
            <span key={`${s.seg_id}-${i}`}> </span>
          ),
        ),
      )}
    </div>
  )
}

function pointer(type: 'pointerdown' | 'pointerover' | 'pointerup', el: Element) {
  fireEvent(
    el,
    new PointerEvent(type, { bubbles: true, pointerType: 'mouse', button: 0 }),
  )
}

describe('usePhraseSelection', () => {
  it('drag over two words selects the range and fires onSelect on pointerup', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-1'))
    pointer('pointerover', screen.getByTestId('w-3'))
    expect(screen.getByTestId('drag-range').textContent).toBe('1-3')
    pointer('pointerup', screen.getByTestId('w-3'))
    expect(onSelect).toHaveBeenCalledWith({ from: 1, to: 3 }, s1)
  })

  it('plain click (no drag) does not fire onSelect', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-1'))
    pointer('pointerup', screen.getByTestId('w-1'))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('reverse drag normalizes the range', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-5'))
    pointer('pointerover', screen.getByTestId('w-2'))
    pointer('pointerup', screen.getByTestId('w-2'))
    expect(onSelect).toHaveBeenCalledWith({ from: 2, to: 5 }, s1)
  })

  it(`clamps to ${MAX_PHRASE_WORDS} words`, () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-0'))
    pointer('pointerover', screen.getByTestId('w-9')) // 10 слов
    pointer('pointerup', screen.getByTestId('w-9'))
    expect(onSelect).toHaveBeenCalledWith({ from: 0, to: 7 }, s1)
  })

  it('clamps to the anchor sentence', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-8'))
    pointer('pointerover', screen.getByTestId('w-11')) // слово из s2
    pointer('pointerup', screen.getByTestId('w-11'))
    expect(onSelect).toHaveBeenCalledWith({ from: 8, to: 9 }, s1)
  })

  it('Escape cancels the drag', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-1'))
    pointer('pointerover', screen.getByTestId('w-3'))
    fireEvent.keyDown(window, { key: 'Escape' })
    pointer('pointerup', screen.getByTestId('w-3'))
    expect(onSelect).not.toHaveBeenCalled()
    expect(screen.getByTestId('drag-range').textContent).toBe('')
  })

  it('touch pointer is ignored', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    fireEvent(
      screen.getByTestId('w-1'),
      new PointerEvent('pointerdown', { bubbles: true, pointerType: 'touch' }),
    )
    pointer('pointerover', screen.getByTestId('w-3'))
    pointer('pointerup', screen.getByTestId('w-3'))
    expect(onSelect).not.toHaveBeenCalled()
  })
})
```

Если jsdom в проекте не имеет `PointerEvent` — добавь в начало теста полифилл:

```ts
if (typeof window !== 'undefined' && !window.PointerEvent) {
  class PointerEventPolyfill extends MouseEvent {
    pointerType: string
    constructor(type: string, init: MouseEventInit & { pointerType?: string } = {}) {
      super(type, init)
      this.pointerType = init.pointerType ?? 'mouse'
    }
  }
  window.PointerEvent = PointerEventPolyfill as unknown as typeof PointerEvent
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && corepack pnpm vitest run src/features/reader/usePhraseSelection.test.tsx`
Expected: FAIL — модуля нет

- [ ] **Step 3: Implement**

```ts
import { useCallback, useEffect, useRef, useState } from 'react'

import { isWord, type Sentence } from '@/api/reader'

/** Диапазон слово-ординалов, включительно, from <= to. */
export interface DragRange {
  from: number
  to: number
}

export const MAX_PHRASE_WORDS = 8

interface Anchor {
  ordinal: number
  sentence: Sentence
  /** Первый/последний слово-ординал предложения якоря (ординалы слов
      внутри предложения — непрерывный диапазон). */
  first: number
  last: number
}

interface Params {
  enabled: boolean
  sentences: Sentence[]
  onSelect: (range: DragRange, sentence: Sentence) => void
}

function clampRange(anchor: Anchor, target: number): DragRange {
  const clamped = Math.min(Math.max(target, anchor.first), anchor.last)
  const span = MAX_PHRASE_WORDS - 1
  const limited =
    clamped > anchor.ordinal
      ? Math.min(clamped, anchor.ordinal + span)
      : Math.max(clamped, anchor.ordinal - span)
  return {
    from: Math.min(anchor.ordinal, limited),
    to: Math.max(anchor.ordinal, limited),
  }
}

function ordinalFromEvent(e: { target: EventTarget | null }): number | null {
  const el = (e.target as HTMLElement | null)?.closest?.('[data-ordinal]')
  if (!el) return null
  const value = Number((el as HTMLElement).dataset.ordinal)
  return Number.isFinite(value) ? value : null
}

export function usePhraseSelection({ enabled, sentences, onSelect }: Params) {
  const [dragRange, setDragRange] = useState<DragRange | null>(null)
  const [dragging, setDragging] = useState(false)
  const anchorRef = useRef<Anchor | null>(null)
  const suppressClickRef = useRef(false)

  const reset = useCallback(() => {
    anchorRef.current = null
    setDragRange(null)
    setDragging(false)
  }, [])

  useEffect(() => {
    if (!dragging) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') reset()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [dragging, reset])

  const onPointerDown: React.PointerEventHandler = (e) => {
    if (!enabled || e.pointerType !== 'mouse' || e.button !== 0) return
    const ordinal = ordinalFromEvent(e)
    if (ordinal === null) return
    const sentence = sentences.find((s) =>
      s.tokens.some((tok) => isWord(tok) && tok.i === ordinal),
    )
    if (!sentence) return
    const words = sentence.tokens.filter(isWord)
    anchorRef.current = {
      ordinal,
      sentence,
      first: words[0].i,
      last: words[words.length - 1].i,
    }
  }

  const onPointerOver: React.PointerEventHandler = (e) => {
    const anchor = anchorRef.current
    if (!anchor) return
    const ordinal = ordinalFromEvent(e)
    if (ordinal === null) return
    if (!dragging && ordinal === anchor.ordinal) return
    setDragging(true)
    setDragRange(clampRange(anchor, ordinal))
  }

  const onPointerUp: React.PointerEventHandler = () => {
    const anchor = anchorRef.current
    if (anchor && dragging && dragRange && dragRange.to > dragRange.from) {
      suppressClickRef.current = true
      onSelect(dragRange, anchor.sentence)
    }
    reset()
  }

  // Предотвращаем нативное выделение текста при drag от слова (click при
  // этом сохраняется). Copy-paste произвольного текста из ридера в v1
  // приносим в жертву механике фраз.
  const onMouseDown: React.MouseEventHandler = (e) => {
    if (!enabled || e.button !== 0) return
    if (ordinalFromEvent(e) !== null) e.preventDefault()
  }

  // Гасим click, синтезируемый браузером после pointerup, завершившего drag,
  // иначе поверх карточки фразы откроется карточка слова.
  const onClickCapture: React.MouseEventHandler = (e) => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false
      e.preventDefault()
      e.stopPropagation()
    }
  }

  return {
    dragRange: dragging ? dragRange : null,
    containerProps: {
      onPointerDown,
      onPointerOver,
      onPointerUp,
      onPointerCancel: reset,
      onMouseDown,
      onClickCapture,
      style: dragging ? ({ userSelect: 'none' } as const) : undefined,
    },
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && corepack pnpm vitest run src/features/reader/usePhraseSelection.test.tsx && corepack pnpm tsc -b`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/reader/usePhraseSelection.ts frontend/src/features/reader/usePhraseSelection.test.tsx
git commit -m "feat(reader): pointer-drag phrase selection state machine"
```

---

### Task 11: TokenSpan — hover-обводка и drag-подсветка

**Files:**
- Modify: `frontend/src/features/reader/TokenSpan.tsx`
- Test: `frontend/src/features/reader/TokenSpan.test.tsx` (дополнить)

**Interfaces:**
- Produces: `TokenSpan` принимает новые опциональные пропсы `dragSelected?: boolean` и `insidePhrase?: boolean`; клик по слову вызывает `e.stopPropagation()`.

- [ ] **Step 1: Add failing tests**

Дополни существующий `TokenSpan.test.tsx` (стиль соседних тестов сохрани):

```tsx
it('applies drag-selection background', () => {
  render(<TokenSpan token={{ t: 'far', n: 'far', i: 1 }} dragSelected />)
  expect(screen.getByText('far').className).toContain('bg-primary/20')
})

it('stops click propagation so PhraseSpan does not also fire', () => {
  const outer = vi.fn()
  render(
    <div onClick={outer}>
      <TokenSpan token={{ t: 'far', n: 'far', i: 1 }} onWordClick={() => {}} />
    </div>,
  )
  fireEvent.click(screen.getByText('far'))
  expect(outer).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && corepack pnpm vitest run src/features/reader/TokenSpan.test.tsx`
Expected: новые тесты FAIL

- [ ] **Step 3: Implement**

`TokenSpan.tsx` — новая версия word-ветки:

```tsx
import { memo } from 'react'

import type { Token, TokenStatusEntry } from '@/api/reader'

interface Props {
  token: Token
  status?: TokenStatusEntry
  dragSelected?: boolean
  insidePhrase?: boolean
  onWordClick?: (word: { t: string; n: string; i: number }) => void
}

export const TokenSpan = memo(function TokenSpan({
  token,
  status,
  dragSelected,
  insidePhrase,
  onWordClick,
}: Props) {
  if ('ws' in token) return <span>{token.ws}</span>
  if ('p' in token) return <span>{token.p}</span>
  const s = status?.s
  const active = s === 'tracked' && (status?.c ?? 0) >= 1
  // Внутри фразы фон слова не рисуем — фон даёт PhraseSpan; статусная
  // подсветка слова вернётся, как только фраза перестанет матчиться.
  const highlight = insidePhrase
    ? ''
    : active
      ? 'rounded bg-[var(--reader-tracked-bg)] px-1 -mx-1'
      : s === 'known' || s === 'ignored'
        ? ''
        : 'rounded bg-[var(--reader-new-bg)] px-1 -mx-1'
  const drag = dragSelected ? 'rounded bg-primary/20' : ''
  return (
    <span
      data-ordinal={token.i}
      role="button"
      tabIndex={-1}
      className={`cursor-pointer rounded hover:ring-1 hover:ring-foreground/40 ${highlight} ${drag}`}
      onClick={(e) => {
        e.stopPropagation()
        onWordClick?.(token)
      }}
    >
      {token.t}
    </span>
  )
})
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && corepack pnpm vitest run src/features/reader/TokenSpan.test.tsx`
Expected: все PASS (включая существующие)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/reader/TokenSpan.tsx frontend/src/features/reader/TokenSpan.test.tsx
git commit -m "feat(reader): token hover ring, drag highlight, click isolation"
```

---

### Task 12: `PhraseSpan` + `SentenceTokens` (рендер ранов)

**Files:**
- Create: `frontend/src/features/reader/PhraseSpan.tsx`
- Create: `frontend/src/features/reader/SentenceTokens.tsx`
- Test: `frontend/src/features/reader/SentenceTokens.test.tsx`
- Modify: `frontend/src/features/reader/PageView.tsx`
- Modify: `frontend/src/features/reader/SentenceView.tsx`

**Interfaces:**
- Consumes: `matchPhrases`, `PhraseIndex`, `PhraseMatch` (Task 9); `TokenSpan` (Task 11); `DragRange` (Task 10).
- Produces (Task 14):

```tsx
// SentenceTokens
interface Props {
  sentence: Sentence
  statuses: StatusMap
  phraseIndex: PhraseIndex
  dragRange: DragRange | null
  onWordClick?: (word: { t: string; n: string; i: number }) => void
  onPhraseClick?: (match: PhraseMatch, sentence: Sentence) => void
}
```
- `PageView`/`SentenceView` получают и пробрасывают `phraseIndex`, `dragRange`, `onPhraseClick` в `SentenceTokens`.

- [ ] **Step 1: Write the failing test**

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Sentence, Token } from '@/api/reader'

import { buildPhraseIndex } from './phraseMatching'
import { SentenceTokens } from './SentenceTokens'

const w = (t: string, i: number): Token => ({ t, n: t.toLowerCase(), i })
const ws: Token = { ws: ' ' }

const sentence: Sentence = {
  seg_id: 's1', index: 0, text: 'so far so good today',
  normalized_text: 'so far so good today',
  tokens: [w('so', 0), ws, w('far', 1), ws, w('so', 2), ws, w('good', 3), ws, w('today', 4)],
}

const index = buildPhraseIndex([
  { item_id: 'ph1', phrase_text: 'so far so good', status: 'tracked', confidence: 1 },
])

describe('SentenceTokens', () => {
  it('wraps a matched phrase and keeps the tail outside', () => {
    render(
      <SentenceTokens
        sentence={sentence} statuses={{}} phraseIndex={index} dragRange={null}
      />,
    )
    const phrase = screen.getByTestId('phrase-span')
    expect(phrase.textContent).toBe('so far so good')
    expect(phrase.textContent).not.toContain('today')
  })

  it('click on the phrase wrapper opens the phrase, not a word', () => {
    const onPhraseClick = vi.fn()
    const onWordClick = vi.fn()
    render(
      <SentenceTokens
        sentence={sentence} statuses={{}} phraseIndex={index} dragRange={null}
        onWordClick={onWordClick} onPhraseClick={onPhraseClick}
      />,
    )
    fireEvent.click(screen.getByTestId('phrase-span'))
    expect(onPhraseClick).toHaveBeenCalledTimes(1)
    expect(onPhraseClick.mock.calls[0][0].entry.itemId).toBe('ph1')
    expect(onWordClick).not.toHaveBeenCalled()
  })

  it('click on a word inside the phrase opens the word only', () => {
    const onPhraseClick = vi.fn()
    const onWordClick = vi.fn()
    render(
      <SentenceTokens
        sentence={sentence} statuses={{}} phraseIndex={index} dragRange={null}
        onWordClick={onWordClick} onPhraseClick={onPhraseClick}
      />,
    )
    fireEvent.click(screen.getByText('far'))
    expect(onWordClick).toHaveBeenCalledWith({ t: 'far', n: 'far', i: 1 })
    expect(onPhraseClick).not.toHaveBeenCalled()
  })

  it('drag range highlights word tokens', () => {
    render(
      <SentenceTokens
        sentence={sentence} statuses={{}} phraseIndex={new Map()}
        dragRange={{ from: 1, to: 3 }}
      />,
    )
    expect(screen.getByText('far').className).toContain('bg-primary/20')
    expect(screen.getByText('today').className).not.toContain('bg-primary/20')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && corepack pnpm vitest run src/features/reader/SentenceTokens.test.tsx`
Expected: FAIL — модулей нет

- [ ] **Step 3: Implement PhraseSpan**

`PhraseSpan.tsx`:

```tsx
import type { ReactNode } from 'react'

interface Props {
  onClick: () => void
  children: ReactNode
}

/**
 * Подложка сохранённой (tracked) фразы. Hover расширяет зону попадания и
 * подложку геометрически (padding + равный отрицательный margin), не сдвигая
 * текст: клик по кромке — карточка фразы, клики по словам внутри гасятся в
 * TokenSpan (stopPropagation).
 */
export function PhraseSpan({ onClick, children }: Props) {
  return (
    <span
      data-testid="phrase-span"
      role="button"
      tabIndex={-1}
      onClick={onClick}
      className="cursor-pointer rounded bg-[var(--reader-tracked-bg)] px-1 -mx-1 py-0.5 -my-0.5 transition-all duration-100 hover:px-2 hover:-mx-2 hover:py-1.5 hover:-my-1.5"
    >
      {children}
    </span>
  )
}
```

- [ ] **Step 4: Implement SentenceTokens**

`SentenceTokens.tsx`:

```tsx
import { useMemo, type ReactNode } from 'react'

import { isWord, type Sentence, type StatusMap } from '@/api/reader'

import { matchPhrases, type PhraseIndex, type PhraseMatch } from './phraseMatching'
import { PhraseSpan } from './PhraseSpan'
import { TokenSpan } from './TokenSpan'
import type { DragRange } from './usePhraseSelection'

interface Props {
  sentence: Sentence
  statuses: StatusMap
  phraseIndex: PhraseIndex
  dragRange: DragRange | null
  onWordClick?: (word: { t: string; n: string; i: number }) => void
  onPhraseClick?: (match: PhraseMatch, sentence: Sentence) => void
}

export function SentenceTokens({
  sentence,
  statuses,
  phraseIndex,
  dragRange,
  onWordClick,
  onPhraseClick,
}: Props) {
  const matches = useMemo(
    () => matchPhrases(sentence.tokens, phraseIndex),
    [sentence, phraseIndex],
  )
  const matchByStart = useMemo(
    () => new Map(matches.map((m) => [m.startIdx, m])),
    [matches],
  )

  const inDrag = (tokIdx: number): boolean => {
    if (!dragRange) return false
    const tok = sentence.tokens[tokIdx]
    return isWord(tok) && tok.i >= dragRange.from && tok.i <= dragRange.to
  }

  const nodes: ReactNode[] = []
  for (let idx = 0; idx < sentence.tokens.length; idx++) {
    const match = matchByStart.get(idx)
    if (match) {
      const { startIdx, endIdx } = match
      nodes.push(
        <PhraseSpan key={`ph-${startIdx}`} onClick={() => onPhraseClick?.(match, sentence)}>
          {sentence.tokens.slice(startIdx, endIdx + 1).map((token, j) => (
            <TokenSpan
              key={startIdx + j}
              token={token}
              status={isWord(token) ? statuses[token.n] : undefined}
              dragSelected={inDrag(startIdx + j)}
              insidePhrase
              onWordClick={onWordClick}
            />
          ))}
        </PhraseSpan>,
      )
      idx = endIdx
      continue
    }
    const token = sentence.tokens[idx]
    nodes.push(
      <TokenSpan
        key={idx}
        token={token}
        status={isWord(token) ? statuses[token.n] : undefined}
        dragSelected={inDrag(idx)}
        onWordClick={onWordClick}
      />,
    )
  }
  return <>{nodes}</>
}
```

- [ ] **Step 5: Thread through PageView and SentenceView**

`PageView.tsx` — новые пропсы и замена цикла токенов:

```tsx
import { Fragment } from 'react'

import type { Sentence, StatusMap } from '@/api/reader'

import type { PageSlice } from './pagination'
import type { PhraseIndex, PhraseMatch } from './phraseMatching'
import { SentenceTokens } from './SentenceTokens'
import type { DragRange } from './usePhraseSelection'

interface Props {
  page: PageSlice
  statuses: StatusMap
  phraseIndex: PhraseIndex
  dragRange: DragRange | null
  onWordClick?: (word: { t: string; n: string; i: number }) => void
  onPhraseClick?: (match: PhraseMatch, sentence: Sentence) => void
}
```

и внутри `<Fragment>` вместо `entry.sentence.tokens.map(...)`:

```tsx
                <SentenceTokens
                  sentence={entry.sentence}
                  statuses={statuses}
                  phraseIndex={phraseIndex}
                  dragRange={dragRange}
                  onWordClick={onWordClick}
                  onPhraseClick={onPhraseClick}
                />
```

`SentenceView.tsx` — те же три новых пропса (`phraseIndex`, `dragRange`, `onPhraseClick`) в `Props`, и внутри `<p className="text-xl leading-[1.8]">` вместо `sentence.tokens.map(...)`:

```tsx
          <SentenceTokens
            sentence={sentence}
            statuses={statuses}
            phraseIndex={phraseIndex}
            dragRange={dragRange}
            onWordClick={onWordClick}
            onPhraseClick={onPhraseClick}
          />
```

(тесты PageView/SentenceView, если падают из-за обязательных пропсов, — передавай `phraseIndex={new Map()}` и `dragRange={null}`.)

- [ ] **Step 6: Run tests**

Run: `cd frontend && corepack pnpm vitest run src/features/reader && corepack pnpm tsc -b`
Expected: SentenceTokens PASS; существующие reader-тесты PASS (после правки пропсов); типы чистые. ReaderPage.tsx пока не передаёт новые пропсы — если tsc падает на ReaderPage, добавь временно `phraseIndex={new Map()} dragRange={null}` в оба вью (Task 14 заменит на реальные).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/reader/PhraseSpan.tsx frontend/src/features/reader/SentenceTokens.tsx frontend/src/features/reader/SentenceTokens.test.tsx frontend/src/features/reader/PageView.tsx frontend/src/features/reader/SentenceView.tsx frontend/src/features/reader/ReaderPage.tsx
git commit -m "feat(reader): phrase underlay rendering with independent inner words"
```

---

### Task 13: WordCard/useWordCard — generalization по kind

**Files:**
- Create: `frontend/src/features/reader/selectedItem.ts`
- Modify: `frontend/src/features/reader/useWordCard.ts`
- Modify: `frontend/src/features/reader/WordCard.tsx`
- Test: `frontend/src/features/reader/WordCard.test.tsx` (дополнить)

**Interfaces:**
- Produces (Task 14):

```ts
// selectedItem.ts
export interface SelectedItem {
  kind: 'token' | 'phrase'
  t: string   // display text (фраза: срез с пунктуацией)
  n: string   // normalized join key
  i: number   // ординал (первого) слова
  sentenceText: string | null // фраза: захвачен при выделении; токен: null
}
```
- `useWordLookup(lang, text, target, kind)`; `wordLookupKey(kind, lang, text, target)`.
- `useWordCardMutations({ kind, lang, text, target, lessonId })` — все мутации с `kind`; при `kind==='phrase'` инвалидируется и `['phrases', lang]`.
- `WordCard` prop `word: SelectedItem | null`; Wiktionary-запрос только для `kind==='token'`.

- [ ] **Step 1: Write failing tests**

Дополни `WordCard.test.tsx` (используй существующие моки файла — там уже замоканы `@/api/vocabulary`, `@/api/dictionary`, `@/api/ai`; следуй локальному стилю рендера):

```tsx
it('phrase card: no dictionary lookup, creates item with kind=phrase', async () => {
  render(
    <WordCard
      word={{ kind: 'phrase', t: 'so far, so good', n: 'so far so good', i: 10, sentenceText: 'So far, so good it is.' }}
      lang="en" target="ru" lessonId="l1" onClose={() => {}} sentenceText={null}
    />,
    { wrapper },
  )
  expect(await screen.findByText('so far, so good')).toBeInTheDocument()
  expect(dictionaryApi.lookup).not.toHaveBeenCalled()
  // выставляем статус — создание item уходит с kind=phrase
  fireEvent.click(screen.getByRole('button', { name: '1' }))
  await waitFor(() =>
    expect(vocabularyApi.createItem).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'phrase', text: 'so far so good' }),
    ),
  )
})

it('token card still queries the dictionary', async () => {
  render(
    <WordCard
      word={{ kind: 'token', t: 'far', n: 'far', i: 1, sentenceText: null }}
      lang="en" target="ru" lessonId="l1" onClose={() => {}} sentenceText="It is far."
    />,
    { wrapper },
  )
  await waitFor(() => expect(dictionaryApi.lookup).toHaveBeenCalled())
})
```

Точные имена wrapper/моков возьми из текущего `WordCard.test.tsx` — правь тесты в его стиле, а не копируй дословно (кнопка `'1'` — из `ConfidencePicker`; проверь её aria-label в существующих тестах и используй его).

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && corepack pnpm vitest run src/features/reader/WordCard.test.tsx`
Expected: новые тесты FAIL (нет kind)

- [ ] **Step 3: Create selectedItem.ts**

```ts
export interface SelectedItem {
  kind: 'token' | 'phrase'
  /** Display text: слово как в тексте / срез фразы с пунктуацией. */
  t: string
  /** Нормализованный join key: token.n / слова фразы через пробел. */
  n: string
  /** Ординал (первого) слова — для поиска предложения и позиционирования. */
  i: number
  /** Для фразы контекст захватывается при выделении; для токена null
      (ReaderPage выводит его по ординалу). */
  sentenceText: string | null
}
```

- [ ] **Step 4: useWordCard.ts — thread kind**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { vocabularyApi } from '@/api/vocabulary'
import type { ItemKind, WriteStatus } from '@/api/vocabulary'

export function wordLookupKey(kind: ItemKind, lang: string, text: string, target: string) {
  return ['word-card', kind, lang, text, target] as const
}

export function useWordLookup(lang: string, text: string | null, target: string, kind: ItemKind) {
  return useQuery({
    queryKey: wordLookupKey(kind, lang, text ?? '', target),
    queryFn: () => vocabularyApi.lookup(lang, text as string, target, kind),
    enabled: text !== null,
  })
}

/**
 * Mutations for the open card. `invalidate()` refreshes the card lookup, the
 * reader token statuses and (for phrases) the reader phrase list.
 */
export function useWordCardMutations(opts: {
  kind: ItemKind
  lang: string
  text: string
  target: string
  lessonId: string | null
}) {
  const qc = useQueryClient()
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: wordLookupKey(opts.kind, opts.lang, opts.text, opts.target) })
    if (opts.kind === 'phrase') {
      void qc.invalidateQueries({ queryKey: ['phrases', opts.lang] })
    }
    if (opts.lessonId !== null) {
      void qc.invalidateQueries({ queryKey: ['reader-statuses', opts.lessonId] })
    }
  }

  const setStatus = useMutation({
    // For a new item (no id) pass itemId=null → create; else patch.
    mutationFn: (v: { itemId: string | null; status: WriteStatus; confidence: number | null }) =>
      v.itemId === null
        ? vocabularyApi.createItem({
            kind: opts.kind, language_code: opts.lang, text: opts.text,
            status: v.status, confidence: v.confidence,
          })
        : vocabularyApi.patchItem(opts.kind, v.itemId, { status: v.status, confidence: v.confidence }),
    onSuccess: invalidate,
  })
  ...
```

В остальных шести мутациях замени первый аргумент `'token'` на `opts.kind` (`saveTranslation`, `updateTranslation`, `deleteTranslation`, `saveNote`, `addTag`, `removeTag`). Больше ничего не меняется.

- [ ] **Step 5: WordCard.tsx — kind-aware**

Точечные правки:

```tsx
import type { SelectedItem } from './selectedItem'

interface Props {
  word: SelectedItem | null
  lang: string
  target: string
  lessonId: string | null
  onClose: () => void
  sentenceText: string | null
}
```

- Удали локальный `interface SelectedWord` из WordCard.tsx.
- `const kind = word?.kind ?? 'token'` — сразу после `expanded`.
- `const lookup = useWordLookup(lang, text, target, kind)`
- `const m = useWordCardMutations({ kind, lang, text: text ?? '', target, lessonId })`
- Wiktionary только для токенов:

```tsx
  const dict = useQuery({
    queryKey: ['dict', lang, target, text ?? ''],
    queryFn: () => dictionaryApi.lookup(lang, target, text as string),
    enabled: text !== null && kind === 'token',
  })
```

- Контекст для AI: `const aiContext = word?.sentenceText ?? sentenceText ?? word?.t ?? ''` (для фразы контекст приходит в `word.sentenceText`, для токена — проп `sentenceText`).
- Больше ничего: AI-запрос, статусы, переводы, заметки, теги уже kind-agnostic после Step 4.

- [ ] **Step 6: Fix ReaderPage call sites (компиляция)**

`ReaderPage.tsx` пока хранит `SelectedWord {t,n,i}` — чтобы tsc собрался до Task 14, адаптируй минимально:

```tsx
import type { SelectedItem } from './selectedItem'
// useState<SelectedWord | null>  ->  useState<SelectedItem | null>
// setSelectedWord из onWordClick:
const handleWordClick = (w: { t: string; n: string; i: number }) =>
  setSelectedWord({ kind: 'token', ...w, sentenceText: null })
```

и передай `handleWordClick` вместо `setSelectedWord` в `PageView`/`SentenceView`. Удали локальный `interface SelectedWord` в ReaderPage.

- [ ] **Step 7: Run tests**

Run: `cd frontend && corepack pnpm vitest run src/features/reader && corepack pnpm tsc -b`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/reader/selectedItem.ts frontend/src/features/reader/useWordCard.ts frontend/src/features/reader/WordCard.tsx frontend/src/features/reader/WordCard.test.tsx frontend/src/features/reader/ReaderPage.tsx
git commit -m "feat(reader): word card handles phrase items (kind-aware lookups)"
```

---

### Task 14: Wiring в ReaderPage + финальная проверка

**Files:**
- Modify: `frontend/src/features/reader/useReaderQueries.ts` (добавить `usePhrases`)
- Modify: `frontend/src/features/reader/ReaderPage.tsx`
- Test: `frontend/src/features/reader/ReaderPage.test.tsx` (дополнить/починить)

**Interfaces:**
- Consumes: всё из Tasks 8–13.
- Produces: рабочий флоу: drag → карточка фразы → сохранение → подложка во всех вхождениях → клик по подложке → карточка.

- [ ] **Step 1: usePhrases hook**

В `useReaderQueries.ts`:

```ts
import { vocabularyApi } from '@/api/vocabulary'

export function usePhrases(lang: string, enabled: boolean) {
  return useQuery({
    queryKey: ['phrases', lang],
    queryFn: () => vocabularyApi.phrases(lang),
    enabled,
  })
}
```

- [ ] **Step 2: ReaderPage wiring**

Правки в `ReaderPage.tsx`:

```tsx
import { buildPhraseIndex, buildSelection, type PhraseMatch } from './phraseMatching'
import { usePhraseSelection } from './usePhraseSelection'
import { usePhrases } from './useReaderQueries'
import type { Sentence } from '@/api/reader'
```

После объявления `flatSentences`:

```tsx
  const contentLang = content?.language_code ?? lang
  const phrases = usePhrases(contentLang, readyForInteraction)
  const phraseIndex = useMemo(() => buildPhraseIndex(phrases.data ?? []), [phrases.data])

  function handlePhraseSelect(range: { from: number; to: number }, sentence: Sentence) {
    const sel = buildSelection(sentence, range.from, range.to)
    if (!sel) return
    setSelectedWord({
      kind: 'phrase', t: sel.displayText, n: sel.text,
      i: sel.firstOrdinal, sentenceText: sentence.text,
    })
  }

  function handlePhraseClick(match: PhraseMatch, sentence: Sentence) {
    const slice = sentence.tokens.slice(match.startIdx, match.endIdx + 1)
    const display = slice
      .map((t) => ('t' in t ? t.t : 'p' in t ? t.p : t.ws))
      .join('')
      .trim()
    const first = slice.find(isWord)
    setSelectedWord({
      kind: 'phrase', t: display, n: match.entry.words.join(' '),
      i: first?.i ?? 0, sentenceText: sentence.text,
    })
  }

  const { dragRange, containerProps } = usePhraseSelection({
    enabled: readyForInteraction,
    sentences: flatSentences,
    onSelect: handlePhraseSelect,
  })
```

Внимание на порядок объявлений: `readyForInteraction` объявлен в файле выше `handleEscape` — перенеси блок фраз ПОСЛЕ строки `const readyForInteraction = ...`.

`selectedSentenceText` учитывает захваченный контекст фразы:

```tsx
  const selectedSentenceText = useMemo(() => {
    if (!selectedWord) return null
    if (selectedWord.sentenceText) return selectedWord.sentenceText
    const sentence = flatSentences.find((s) =>
      s.tokens.some((tok) => isWord(tok) && tok.i === selectedWord.i),
    )
    return sentence?.text ?? null
  }, [selectedWord, flatSentences])
```

Контейнер контента получает обработчики драга:

```tsx
      <div
        className={cn('py-6', fontClass)}
        onTouchStart={swipeHandlers.onTouchStart}
        onTouchEnd={swipeHandlers.onTouchEnd}
        {...containerProps}
      >
```

Оба вью получают реальные значения (заменить временные из Task 12):

```tsx
            <PageView
              page={currentPage} statuses={statusMap}
              phraseIndex={phraseIndex} dragRange={dragRange}
              onWordClick={handleWordClick} onPhraseClick={handlePhraseClick}
            />
            ...
            <SentenceView
              lessonId={lessonId} sentence={currentSentence} statuses={statusMap}
              lang={content.language_code} targetLang={DEFAULT_TRANSLATION_LANG}
              phraseIndex={phraseIndex} dragRange={dragRange}
              onWordClick={handleWordClick} onPhraseClick={handlePhraseClick}
            />
```

- [ ] **Step 3: Add an integration test**

Дополни `ReaderPage.test.tsx` (в стиле существующих тестов файла — там уже есть моки lesson/content/statuses; добавь мок `vocabularyApi.phrases`, возвращающий одну tracked-фразу, реально встречающуюся в замоканном контенте):

```tsx
it('renders saved phrase underlay and opens phrase card on click', async () => {
  // arrange: phrases -> [{ item_id: 'ph1', phrase_text: '<два слова из мокового контента>', status: 'tracked', confidence: 1 }]
  renderReaderPage()
  const phrase = await screen.findByTestId('phrase-span')
  fireEvent.click(phrase)
  expect(await screen.findByTestId('word-card')).toBeInTheDocument()
})
```

Конкретные слова возьми из мокового контента, который уже есть в этом файле теста.

- [ ] **Step 4: Full frontend suite + lint + types**

Run: `cd frontend && corepack pnpm vitest run && corepack pnpm tsc -b && corepack pnpm lint`
Expected: всё PASS

- [ ] **Step 5: Full backend suite**

Run: `cd backend && uv run pytest -q && uv run ruff check src tests`
Expected: PASS

- [ ] **Step 6: Manual smoke (playwright-cli)**

Подними dev-окружение (docker-compose.dev.yml / dev-серверы как принято в проекте), открой урок и проверь руками через скилл `playwright-cli`:
1. hover слова — обводка;
2. drag ЛКМ через 3 слова → карточка фразы, AI-подсказка приходит;
3. сохранить перевод + статус 1 → подложка появилась во всех вхождениях предложения/страницы;
4. клик по слову внутри подложки → карточка слова; клик по кромке фразы (hover-расширение) → карточка фразы;
5. drag через границу предложения — выделение остановилось на границе; drag 10 слов — остановилось на 8;
6. Esc во время drag — отмена;
7. страница Vocabulary — фраза в списке.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/reader/ReaderPage.tsx frontend/src/features/reader/ReaderPage.test.tsx frontend/src/features/reader/useReaderQueries.ts
git commit -m "feat(reader): drag-select phrases wired end-to-end"
```

---

## Self-Review (выполнен при написании плана)

- **Spec coverage:** hover-обводка (T11), drag+кламп 8+границы предложения+Esc+мышь (T10), карточка фразы = док-панель с AI/без Wiktionary (T13), сохранение/upsert/2–8 слов (T4), подсветка везде leftmost-longest только по словам (T9, T12), клики слово-внутри-фразы vs кромка (T11, T12), phrase list endpoint (T5), Vocabulary список+bulk (T6, T7), инвалидация `['phrases', lang]` (T13), деградация AI/ошибок — существующие паттерны WordCard не тронуты (T13).
- **Types:** `SelectedItem` (T13) = использует ReaderPage (T14); `PhraseIndex/PhraseMatch/DragRange` согласованы между T9/T10/T12/T14; `kind` сигнатуры сервиса — существующие, реализация обобщена.
- **Известное упрощение:** внутри фразы статусная подсветка слов заменяется подложкой фразы (см. `insidePhrase`); слова остаются кликабельными — осознанное решение v1.
