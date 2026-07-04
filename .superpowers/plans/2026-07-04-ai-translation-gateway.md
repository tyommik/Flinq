# AI Translation Gateway (FLQ-3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /api/ai/translate` — contextual word translation via one OpenAI-compatible adapter, returning 1–3 LingQ-style hint variants, with metadata-only audit and a hard kill-switch.

**Architecture:** New `flinq/modules/ai_translation/` in thin layers: `prompts.py` (pure prompt build/parse), `provider.py` (httpx adapter + retries, the only HTTP-facing layer), `models.py` (`ai_requests`, migration 0005), `service.py` (orchestration + audit), `api/ai.py`. No cache, no Redis, no lesson-table reads — the gateway is fully decoupled from content storage.

**Tech Stack:** Python 3.13, FastAPI, httpx (existing dep), SQLAlchemy 2 async, Alembic, loguru, pytest + testcontainers. No new dependencies.

**Spec:** `.superpowers/specs/2026-07-04-ai-translation-gateway-design.md` — read it first; decisions there are binding (including the two recorded ADR deviations).

## Global Constraints

- Branch: `feature/FLQ-3-ai-translation-gateway` off current `main` (note: `feature/` prefix — user convention as of FLQ-3).
- Gates green after every task (run from `backend/`): `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` (0 errors), `uv run pytest`.
- Commits (AGENTS.md «Git конвенции»): `feat(FLQ-3.<task#>): <english imperative subject, ≤72 chars>`; body answers "why"; always scoped paths `git commit -m "..." -- <exact paths>`; NO Co-Authored-By.
- Do NOT edit `README.md`, `docs/adr/*`, `.github/workflows/*`, `backend/Dockerfile`, `AGENTS.md` — uncommitted user WIP lives there.
- PRIVACY (ADR-0003, binding): raw `surface_text`/`context_text`/prompt/model response must NEVER appear in loguru calls or in `ai_requests` — only hashes, counts, latencies, statuses, error codes.
- UNICODE: tests contain Cyrillic ("позже", "потом", "Увидимся позже!"). Copy byte-exactly; sanity-check with `grep -c "позже" <file>` after writing (this project was burned by homoglyph transcription in FLQ-2 Task 1).
- New code: `from __future__ import annotations`, full type annotations, `Mapped[...]` ORM style.

---

### Task 0: Branch

- [ ] **Step 1:**

```bash
git checkout main && git pull --ff-only && git checkout -b feature/FLQ-3-ai-translation-gateway
```

---

### Task 1: Prompts — build + parse (pure functions)

**Files:**
- Create: `backend/src/flinq/modules/ai_translation/__init__.py` (docstring: `"""AI translation gateway: contextual hint translation via one OpenAI-compatible provider (FLQ-3, ADR-0003)."""`)
- Create: `backend/src/flinq/modules/ai_translation/prompts.py`
- Test: `backend/tests/modules/ai_translation/__init__.py` (empty), `backend/tests/modules/ai_translation/test_prompts.py`

**Interfaces:**
- Produces: `normalize_ai_text(text: str) -> str`, `build_hints_prompt(*, surface_text: str, context_text: str, target_language_code: str) -> tuple[str, str]` (returns `(system, user)`), `parse_hints(text: str) -> list[str]`, `LANGUAGE_NAMES: dict[str, str]`. Task 4 consumes all of these.

- [ ] **Step 1: Write the failing tests**

`backend/tests/modules/ai_translation/test_prompts.py`:

```python
"""Prompt build/parse: deterministic bytes, LingQ-style hint parsing (spec Decisions 1-2)."""

from __future__ import annotations

from flinq.modules.ai_translation.prompts import (
    build_hints_prompt,
    normalize_ai_text,
    parse_hints,
)


def test_normalize_collapses_whitespace_and_nfc() -> None:
    assert normalize_ai_text("  See \n you\t later!  ") == "See you later!"
    # NFC: е + U+0301 combining acute -> single precomposed char
    assert normalize_ai_text("é") == "é"


def test_prompt_is_deterministic_and_contains_parts() -> None:
    a = build_hints_prompt(surface_text="later", context_text="See you later!", target_language_code="ru")
    b = build_hints_prompt(surface_text=" later ", context_text="See  you later!", target_language_code="ru")
    assert a == b  # normalization makes trivial client differences irrelevant
    system, user = a
    assert "one per line" in system
    assert "Sentence: See you later!" in user
    assert "Word or phrase: later" in user
    assert "into Russian" in user


def test_parse_hints_plain_lines() -> None:
    assert parse_hints("позже\nпотом\n") == ["позже", "потом"]


def test_parse_hints_strips_numbering_bullets_quotes() -> None:
    text = '1. «позже»\n- "потом"\n* спустя\n'
    assert parse_hints(text) == ["позже", "потом", "спустя"]


def test_parse_hints_dedupes_and_caps_at_three() -> None:
    text = "позже\nпозже\nпотом\nспустя\nпозднее\n"
    assert parse_hints(text) == ["позже", "потом", "спустя"]


def test_parse_hints_empty_and_garbage() -> None:
    assert parse_hints("") == []
    assert parse_hints("\n \n- \n") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/modules/ai_translation/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: flinq.modules.ai_translation`

- [ ] **Step 3: Implement `prompts.py`**

```python
"""Hardcoded contextual-translation prompt + hint parsing (spec Decisions 1-2).

Pure functions, no I/O. The prompt is deterministic: inputs are normalized
(NFC + whitespace collapse) so the audit prompt_hash is stable against
trivial client-side differences in how the sentence was cut.
"""

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
_LEAD_JUNK_RE = re.compile(r"^\s*(?:[-*•·]+|\d+[.)])\s*")
_QUOTES = "\"'«»„“”‚‘’"

LANGUAGE_NAMES: dict[str, str] = {"en": "English", "ru": "Russian", "pt": "Portuguese"}

SYSTEM_PROMPT = (
    "You are a translation assistant inside a language-learning reader. "
    "Reply with 1 to 3 short translation variants only, one per line, best first. "
    "No numbering, no explanations, no quotes."
)


def normalize_ai_text(text: str) -> str:
    """NFC + collapse whitespace runs + strip. Keeps the prompt (and its hash) stable."""
    return _WS_RE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def build_hints_prompt(
    *, surface_text: str, context_text: str, target_language_code: str
) -> tuple[str, str]:
    """Return (system, user) messages for the hints request."""
    surface = normalize_ai_text(surface_text)
    context = normalize_ai_text(context_text)
    user = (
        f"Sentence: {context}\n"
        f"Word or phrase: {surface}\n"
        f"Translate the word or phrase as it is used in this sentence "
        f"into {LANGUAGE_NAMES[target_language_code]}."
    )
    return SYSTEM_PROMPT, user


def parse_hints(text: str) -> list[str]:
    """Model output -> up to 3 clean, deduplicated hint strings (order preserved)."""
    hints: list[str] = []
    for line in text.splitlines():
        cleaned = _LEAD_JUNK_RE.sub("", line).strip().strip(_QUOTES).strip()
        if cleaned and cleaned not in hints:
            hints.append(cleaned)
        if len(hints) == 3:
            break
    return hints
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/modules/ai_translation/test_prompts.py -v`
Expected: PASS (6 tests). Note the U+2019 in `_QUOTES` is intentional (curly apostrophe as quote char) — if ruff flags RUF001, add a scoped `# noqa: RUF001` like `core/textnorm.py` does.

- [ ] **Step 5: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
git add backend/src/flinq/modules/ai_translation backend/tests/modules/ai_translation
git commit -m "feat(FLQ-3.1): add hints prompt builder and parser" -- backend/src/flinq/modules/ai_translation backend/tests/modules/ai_translation
```

---

### Task 2: `ai_requests` model + migration 0005

**Files:**
- Create: `backend/src/flinq/modules/ai_translation/models.py`
- Create: `backend/migrations/versions/0005_ai_requests.py`
- Test: `backend/tests/modules/ai_translation/test_models_schema.py`
- Modify: `backend/tests/conftest.py` (`_init_schema` — add the ai_translation side-effect import next to the existing three)

**Interfaces:**
- Produces: ORM class `AIRequest` with fields exactly as below; Task 4 constructs it.

- [ ] **Step 1: Write the failing test**

`backend/tests/modules/ai_translation/test_models_schema.py`:

```python
"""ai_requests schema: metadata-only audit row round-trip, user FK cascade (spec Decision 5)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.ai_translation.models import AIRequest
from flinq.modules.identity.repo import UserRepo


async def _make_user(session: AsyncSession) -> uuid.UUID:
    user = await UserRepo(session).create(
        email=f"ai-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name="T",
        role="learner",
    )
    await session.flush()
    return user.id


async def test_audit_row_round_trip(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    row = AIRequest(
        request_id=uuid.uuid4(),
        user_id=user_id,
        lesson_id=None,
        provider="api.openai.com",
        model="gpt-4o-mini",
        prompt_hash="a" * 64,
        selected_text_hash="b" * 64,
        input_tokens=42,
        output_tokens=7,
        latency_ms=840,
        success=True,
        error_code=None,
    )
    db_session.add(row)
    await db_session.flush()
    loaded = await db_session.get(AIRequest, row.id)
    assert loaded is not None
    assert loaded.success is True
    assert loaded.created_at is not None
    assert loaded.item_kind is None and loaded.item_id is None


async def test_user_delete_cascades_audit(db_session: AsyncSession) -> None:
    user_id = await _make_user(db_session)
    db_session.add(
        AIRequest(
            request_id=uuid.uuid4(),
            user_id=user_id,
            provider="p",
            model="m",
            prompt_hash="a" * 64,
            selected_text_hash="b" * 64,
            latency_ms=1,
            success=False,
            error_code="provider_unavailable",
        )
    )
    await db_session.flush()
    from flinq.modules.identity.models import User

    user = await db_session.get(User, user_id)
    assert user is not None
    await db_session.delete(user)
    await db_session.flush()
    db_session.expire_all()  # DB-level cascade; identity map is stale (see FLQ-2 pattern)
    count = await db_session.scalar(
        select(func.count()).select_from(AIRequest).where(AIRequest.user_id == user_id)
    )
    assert count == 0
```

- [ ] **Step 2: Run to verify failure** (`ModuleNotFoundError` on models import)

- [ ] **Step 3: Implement `models.py`**

```python
"""Metadata-only AI audit (domain model §11.1, ADR-0003 privacy rules).

Raw prompt / selected text / model response are NEVER stored here — hashes,
counts and statuses only. lesson_id deliberately has NO foreign key: the
gateway is decoupled from lesson lifecycle (spec Deviation 2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from flinq.core.db import Base


class AIRequest(Base):
    __tablename__ = "ai_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # no FK: decoupled
    item_kind: Mapped[str | None] = mapped_column(String(16))  # reserved, NULL in MVP
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # reserved
    provider: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(255))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    selected_text_hash: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean)
    error_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_ai_requests_user_created", "user_id", "created_at"),)
```

- [ ] **Step 4: Register models in test schema bootstrap**

In `backend/tests/conftest.py` `_init_schema`, next to the three existing side-effect imports:

```python
    from flinq.modules.ai_translation import (
        models as _ai_models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    )
```

- [ ] **Step 5: Run tests to verify pass** (`uv run pytest tests/modules/ai_translation/test_models_schema.py -v` → 2 PASS)

- [ ] **Step 6: Write migration `0005_ai_requests.py`**

Follow `0004_dictionary.py` style: `revision = "0005_ai_requests"`, `down_revision = "0004_dictionary"`. `upgrade()`: create `ai_requests` mirroring the model 1:1 (sa.Column, `postgresql.UUID(as_uuid=True)`, FK `users.id ondelete="CASCADE"`, nullability per model, `server_default=sa.text("now()")` for created_at) + `op.create_index("ix_ai_requests_user_created", "ai_requests", ["user_id", "created_at"])`. `downgrade()`: drop index, drop table.

- [ ] **Step 7: Verify migration chain** (`uv run pytest tests/modules/lesson_library/test_migration_chain.py -v` → PASS with 0005 in the chain)

- [ ] **Step 8: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
git add backend/src/flinq/modules/ai_translation/models.py backend/migrations/versions/0005_ai_requests.py backend/tests/modules/ai_translation/test_models_schema.py backend/tests/conftest.py
git commit -m "feat(FLQ-3.2): add ai_requests audit model and migration" -- backend/src/flinq/modules/ai_translation/models.py backend/migrations/versions/0005_ai_requests.py backend/tests/modules/ai_translation/test_models_schema.py backend/tests/conftest.py
```

---

### Task 3: OpenAI-compatible provider (httpx + retries)

**Files:**
- Create: `backend/src/flinq/modules/ai_translation/provider.py`
- Test: `backend/tests/modules/ai_translation/test_provider.py`

**Interfaces:**
- Produces: `LLMProvider` (Protocol with `async def complete(self, *, system: str, user: str) -> LLMCompletion`), `LLMCompletion(text, input_tokens, output_tokens)` frozen dataclass, `OpenAICompatibleProvider(settings, *, client=None)`, exceptions `ProviderUnavailable`, `ProviderRejected`. Task 4 consumes all.

- [ ] **Step 1: Write the failing tests**

`backend/tests/modules/ai_translation/test_provider.py`:

```python
"""OpenAICompatibleProvider: retry discipline per ADR-0003 (3 attempts, network/5xx only)."""

from __future__ import annotations

import httpx
import pytest

from flinq.core.config import Settings
from flinq.modules.ai_translation import provider as provider_mod
from flinq.modules.ai_translation.provider import (
    OpenAICompatibleProvider,
    ProviderRejected,
    ProviderUnavailable,
)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "llm_enabled": True,
        "llm_base_url": "https://llm.test/v1",
        "llm_api_key": "sk-test",
        "llm_model": "test-model",
        "llm_timeout_seconds": 5,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "позже\nпотом"}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 7},
        },
    )


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_mod, "_BACKOFF_BASE_SECONDS", 0.0)


async def test_success_parses_text_and_usage() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok_response()

    p = OpenAICompatibleProvider(_settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    completion = await p.complete(system="s", user="u")
    assert completion.text == "позже\nпотом"
    assert completion.input_tokens == 42 and completion.output_tokens == 7
    [request] = seen
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test"


async def test_no_auth_header_when_key_empty() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok_response()

    p = OpenAICompatibleProvider(_settings(llm_api_key=""), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await p.complete(system="s", user="u")
    assert "authorization" not in seen[0].headers


async def test_retries_5xx_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500, text="boom")
        return _ok_response()

    p = OpenAICompatibleProvider(_settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    completion = await p.complete(system="s", user="u")
    assert completion.text and calls["n"] == 3


async def test_persistent_5xx_raises_after_exactly_three_attempts() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="down")

    p = OpenAICompatibleProvider(_settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderUnavailable):
        await p.complete(system="s", user="u")
    assert calls["n"] == 3


async def test_transport_error_retried_then_raises() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("timeout")

    p = OpenAICompatibleProvider(_settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderUnavailable):
        await p.complete(system="s", user="u")
    assert calls["n"] == 3


async def test_4xx_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    p = OpenAICompatibleProvider(_settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderRejected):
        await p.complete(system="s", user="u")
    assert calls["n"] == 1


async def test_malformed_body_raises_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    p = OpenAICompatibleProvider(_settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderRejected):
        await p.complete(system="s", user="u")
```

- [ ] **Step 2: Run to verify failure** (no `provider` module)

- [ ] **Step 3: Implement `provider.py`**

```python
"""The one OpenAI-compatible LLM adapter (ADR-0003). Only HTTP-facing layer.

Retry discipline: up to 3 attempts, exponential backoff, ONLY on transport
errors and 5xx. Provider 4xx (bad key/model) fails immediately. Privacy:
never log message contents — status codes and attempt counts only.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

import httpx
from loguru import logger

from flinq.core.config import Settings

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5


class ProviderUnavailable(Exception):
    """Network failure, timeout or 5xx after all retries."""


class ProviderRejected(Exception):
    """Non-retriable provider response (4xx or malformed body)."""


@dataclass(frozen=True)
class LLMCompletion:
    text: str
    input_tokens: int | None
    output_tokens: int | None


class LLMProvider(Protocol):
    async def complete(self, *, system: str, user: str) -> LLMCompletion: ...


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        s = self._settings
        payload = {
            "model": s.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 100,
        }
        headers: dict[str, str] = {}
        if s.llm_api_key:
            headers["Authorization"] = f"Bearer {s.llm_api_key}"
        url = f"{s.llm_base_url.rstrip('/')}/chat/completions"

        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=float(s.llm_timeout_seconds))
        try:
            last_error: Exception | None = None
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    response = await client.post(url, json=payload, headers=headers)
                except httpx.TransportError as exc:
                    last_error = exc
                    logger.warning(
                        "llm attempt {}/{}: {}", attempt, _MAX_ATTEMPTS, type(exc).__name__
                    )
                else:
                    if response.status_code < 400:
                        return _parse_completion(response)
                    if response.status_code < 500:
                        raise ProviderRejected(f"provider returned {response.status_code}")
                    last_error = ProviderUnavailable(f"provider returned {response.status_code}")
                    logger.warning(
                        "llm attempt {}/{}: HTTP {}", attempt, _MAX_ATTEMPTS, response.status_code
                    )
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(_BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
            raise ProviderUnavailable(str(last_error)) from last_error
        finally:
            if own_client:
                await client.aclose()


def _parse_completion(response: httpx.Response) -> LLMCompletion:
    body = response.json()
    try:
        text = body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderRejected("malformed provider response") from exc
    usage = body.get("usage") or {}
    return LLMCompletion(
        text=text,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
    )
```

- [ ] **Step 4: Run to verify pass** (7 tests)

- [ ] **Step 5: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
git add backend/src/flinq/modules/ai_translation/provider.py backend/tests/modules/ai_translation/test_provider.py
git commit -m "feat(FLQ-3.3): add OpenAI-compatible provider with retry discipline" -- backend/src/flinq/modules/ai_translation/provider.py backend/tests/modules/ai_translation/test_provider.py
```

---

### Task 4: Service orchestration + audit

**Files:**
- Create: `backend/src/flinq/modules/ai_translation/service.py`
- Test: `backend/tests/modules/ai_translation/test_service.py`

**Interfaces:**
- Consumes: Tasks 1–3 outputs.
- Produces (Task 5 consumes): `TranslationHints(hints: list[str], model: str, latency_ms: int)` frozen dataclass; `AIDisabled(Exception)`, `AIEmptyResponse(Exception)`; `async def translate_hints(session, *, user_id: uuid.UUID, surface_text: str, context_text: str, target_language_code: str, lesson_id: uuid.UUID | None = None, provider: LLMProvider | None = None) -> TranslationHints`; `_default_provider() -> LLMProvider` (module function — API tests monkeypatch it).

- [ ] **Step 1: Write the failing tests**

`backend/tests/modules/ai_translation/test_service.py`:

```python
"""translate_hints orchestration: audit rows, kill-switch, privacy (spec Decision 4)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.config import get_settings
from flinq.modules.ai_translation import service
from flinq.modules.ai_translation.models import AIRequest
from flinq.modules.ai_translation.provider import LLMCompletion, ProviderUnavailable
from flinq.modules.identity.repo import UserRepo

SURFACE = "later"
CONTEXT = "See you later!"


class FakeProvider:
    def __init__(self, *, text: str = "позже\nпотом", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls = 0

    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMCompletion(text=self.text, input_tokens=42, output_tokens=7)


@pytest.fixture(autouse=True)
def _llm_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", True)


@pytest.fixture(autouse=True)
async def _clean_audit(db_session: AsyncSession) -> None:
    yield
    from sqlalchemy import delete

    await db_session.execute(delete(AIRequest))
    await db_session.commit()


async def _user(db_session: AsyncSession) -> uuid.UUID:
    user = await UserRepo(db_session).create(
        email=f"svc-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name="T",
        role="learner",
    )
    await db_session.flush()
    return user.id


async def _audit_rows(db_session: AsyncSession) -> list[AIRequest]:
    return list((await db_session.scalars(select(AIRequest))).all())


async def test_success_returns_hints_and_audits(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    result = await service.translate_hints(
        db_session,
        user_id=user_id,
        surface_text=SURFACE,
        context_text=CONTEXT,
        target_language_code="ru",
        provider=FakeProvider(),
    )
    assert result.hints == ["позже", "потом"]
    assert result.latency_ms >= 0
    [row] = await _audit_rows(db_session)
    assert row.success is True and row.error_code is None
    assert row.input_tokens == 42 and row.output_tokens == 7
    assert len(row.prompt_hash) == 64 and len(row.selected_text_hash) == 64


async def test_provider_failure_audits_and_reraises(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    with pytest.raises(ProviderUnavailable):
        await service.translate_hints(
            db_session,
            user_id=user_id,
            surface_text=SURFACE,
            context_text=CONTEXT,
            target_language_code="ru",
            provider=FakeProvider(error=ProviderUnavailable("down")),
        )
    [row] = await _audit_rows(db_session)
    assert row.success is False and row.error_code == "provider_unavailable"


async def test_empty_model_output_raises_and_audits(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    with pytest.raises(service.AIEmptyResponse):
        await service.translate_hints(
            db_session,
            user_id=user_id,
            surface_text=SURFACE,
            context_text=CONTEXT,
            target_language_code="ru",
            provider=FakeProvider(text="\n \n"),
        )
    [row] = await _audit_rows(db_session)
    assert row.success is False and row.error_code == "empty_response"


async def test_kill_switch_no_call_no_audit(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", False)
    user_id = await _user(db_session)
    fake = FakeProvider()
    with pytest.raises(service.AIDisabled):
        await service.translate_hints(
            db_session,
            user_id=user_id,
            surface_text=SURFACE,
            context_text=CONTEXT,
            target_language_code="ru",
            provider=fake,
        )
    assert fake.calls == 0
    assert await _audit_rows(db_session) == []


async def test_privacy_audit_contains_no_raw_text(db_session: AsyncSession) -> None:
    user_id = await _user(db_session)
    await service.translate_hints(
        db_session,
        user_id=user_id,
        surface_text=SURFACE,
        context_text=CONTEXT,
        target_language_code="ru",
        provider=FakeProvider(),
    )
    [row] = await _audit_rows(db_session)
    dump = " ".join(str(v) for v in vars(row).values())
    assert SURFACE not in dump.replace(row.selected_text_hash, "")
    assert CONTEXT not in dump
    assert "позже" not in dump
```

- [ ] **Step 2: Run to verify failure** (no `service` module)

- [ ] **Step 3: Implement `service.py`**

```python
"""translate_hints: kill-switch -> provider -> parse -> metadata-only audit.

The audit write is best-effort: its failure is logged, never masks the
user-facing result (FLQ-2 final-review lesson). Raw text never reaches
loguru or the audit table (ADR-0003).
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.config import get_settings
from flinq.modules.ai_translation.models import AIRequest
from flinq.modules.ai_translation.prompts import build_hints_prompt, normalize_ai_text, parse_hints
from flinq.modules.ai_translation.provider import (
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderRejected,
    ProviderUnavailable,
)


class AIDisabled(Exception):
    """FLINQ_LLM_ENABLED is false — no calls, no audit (ADR-0003 kill-switch)."""


class AIEmptyResponse(Exception):
    """Provider answered, but nothing parseable came back."""


@dataclass(frozen=True)
class TranslationHints:
    hints: list[str]
    model: str
    latency_ms: int


def _default_provider() -> LLMProvider:
    return OpenAICompatibleProvider(get_settings())


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def translate_hints(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    surface_text: str,
    context_text: str,
    target_language_code: str,
    lesson_id: uuid.UUID | None = None,
    provider: LLMProvider | None = None,
) -> TranslationHints:
    settings = get_settings()
    if not settings.llm_enabled:
        raise AIDisabled

    provider = provider or _default_provider()
    system, user = build_hints_prompt(
        surface_text=surface_text,
        context_text=context_text,
        target_language_code=target_language_code,
    )
    prompt_hash = _sha256(system + "\n" + user)
    selected_text_hash = _sha256(normalize_ai_text(surface_text))
    request_id = uuid.uuid4()
    started = time.monotonic()

    async def audit(
        *,
        success: bool,
        error_code: str | None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        try:
            session.add(
                AIRequest(
                    request_id=request_id,
                    user_id=user_id,
                    lesson_id=lesson_id,
                    provider=urlparse(settings.llm_base_url).netloc or settings.llm_base_url,
                    model=settings.llm_model,
                    prompt_hash=prompt_hash,
                    selected_text_hash=selected_text_hash,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    success=success,
                    error_code=error_code,
                )
            )
            await session.commit()
        except Exception:
            logger.exception("ai_requests audit write failed (request_id={})", request_id)

    try:
        completion = await provider.complete(system=system, user=user)
    except ProviderUnavailable:
        await audit(success=False, error_code="provider_unavailable")
        raise
    except ProviderRejected:
        await audit(success=False, error_code="provider_rejected")
        raise

    latency_ms = int((time.monotonic() - started) * 1000)
    hints = parse_hints(completion.text)
    if not hints:
        await audit(
            success=False,
            error_code="empty_response",
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )
        raise AIEmptyResponse
    await audit(
        success=True,
        error_code=None,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
    )
    logger.info(
        "ai translate ok (request_id={}, latency_ms={}, hints={})",
        request_id,
        latency_ms,
        len(hints),
    )
    return TranslationHints(hints=hints, model=settings.llm_model, latency_ms=latency_ms)
```

- [ ] **Step 4: Run to verify pass** (5 tests)

- [ ] **Step 5: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
git add backend/src/flinq/modules/ai_translation/service.py backend/tests/modules/ai_translation/test_service.py
git commit -m "feat(FLQ-3.4): add translate_hints service with metadata-only audit" -- backend/src/flinq/modules/ai_translation/service.py backend/tests/modules/ai_translation/test_service.py
```

---

### Task 5: Schemas + endpoint + wiring

**Files:**
- Create: `backend/src/flinq/modules/ai_translation/schemas.py`
- Create: `backend/src/flinq/api/ai.py`
- Modify: `backend/src/flinq/main.py` (import + `app.include_router(ai_router)` after `dictionary_router`)
- Test: `backend/tests/api/test_ai_translate.py`

**Interfaces:**
- Consumes: Task 4's `translate_hints`, exceptions, `_default_provider`.
- Produces: `POST /api/ai/translate` per the spec contract.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_ai_translate.py` (copy the `_register_and_onboard` helper from `tests/api/test_dictionary_lookup.py`; tests self-contained):

```python
"""POST /api/ai/translate — contract per spec (401/422/503/502/200)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.config import get_settings
from flinq.main import create_app
from flinq.modules.ai_translation import service
from flinq.modules.ai_translation.provider import LLMCompletion, ProviderUnavailable

BODY = {"surface_text": "later", "context_text": "See you later!", "target_language_code": "ru"}


async def _register_and_onboard(c: AsyncClient, email: str, lang: str = "en") -> str:
    r = await c.post(
        "/auth/register",
        json={"display_name": "T", "email": email, "password": "abcdefghij"},
    )
    assert r.status_code == 201
    csrf = c.cookies.get("flinq_csrf")
    assert csrf
    await c.post(
        "/me/onboarding",
        json={"ui_language": "en", "learning_languages": [lang], "translation_language": "ru"},
        headers={"X-CSRF-Token": csrf},
    )
    return csrf


class _GoodProvider:
    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        return LLMCompletion(text="позже\nпотом", input_tokens=1, output_tokens=1)


class _DownProvider:
    async def complete(self, *, system: str, user: str) -> LLMCompletion:
        raise ProviderUnavailable("down")


@pytest.fixture(autouse=True)
def _llm_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", True)


@pytest.fixture(autouse=True)
async def _clean_audit(db_session: AsyncSession) -> None:
    yield
    from sqlalchemy import delete

    from flinq.modules.ai_translation.models import AIRequest

    await db_session.execute(delete(AIRequest))
    await db_session.commit()


async def test_translate_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_default_provider", lambda: _GoodProvider())
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "ai-ok@example.com")
        r = await c.post("/api/ai/translate", json=BODY, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        body = r.json()
        assert [h["text"] for h in body["hints"]] == ["позже", "потом"]
        assert body["model"] and isinstance(body["latency_ms"], int)


async def test_translate_requires_auth() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/ai/translate", json=BODY)
        assert r.status_code == 401


async def test_translate_validation() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "ai-422@example.com")
        for bad in (
            {**BODY, "surface_text": "y" * 257},
            {**BODY, "context_text": "y" * 1001},
            {**BODY, "target_language_code": "xx"},
            {**BODY, "surface_text": ""},
        ):
            r = await c.post("/api/ai/translate", json=bad, headers={"X-CSRF-Token": csrf})
            assert r.status_code == 422


async def test_translate_kill_switch_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_enabled", False)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "ai-503@example.com")
        r = await c.post("/api/ai/translate", json=BODY, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 503
        assert r.json()["detail"] == "ai_disabled"


async def test_translate_provider_down_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_default_provider", lambda: _DownProvider())
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        csrf = await _register_and_onboard(c, "ai-502@example.com")
        r = await c.post("/api/ai/translate", json=BODY, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 502
        assert r.json()["detail"] == "ai_provider_error"
```

- [ ] **Step 2: Run to verify failure** (404 route)

- [ ] **Step 3: Implement**

`schemas.py`:

```python
"""Request/response models for the AI translate endpoint."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    surface_text: str = Field(min_length=1, max_length=256)
    context_text: str = Field(min_length=1, max_length=1000)
    target_language_code: Literal["en", "ru", "pt"]
    lesson_id: uuid.UUID | None = None


class HintOut(BaseModel):
    text: str


class TranslateResponse(BaseModel):
    hints: list[HintOut]
    model: str
    latency_ms: int
```

`api/ai.py`:

```python
"""AI contextual translation API (spec: FLQ-3)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.core.db import get_session
from flinq.modules.ai_translation import service
from flinq.modules.ai_translation.provider import ProviderRejected, ProviderUnavailable
from flinq.modules.ai_translation.schemas import HintOut, TranslateRequest, TranslateResponse

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _require_user(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return user_id


@router.post("/translate", response_model=TranslateResponse)
async def translate(
    request: Request,
    body: TranslateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranslateResponse:
    user_id = _require_user(request)
    try:
        result = await service.translate_hints(
            session,
            user_id=user_id,
            surface_text=body.surface_text,
            context_text=body.context_text,
            target_language_code=body.target_language_code,
            lesson_id=body.lesson_id,
        )
    except service.AIDisabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="ai_disabled") from None
    except (ProviderUnavailable, ProviderRejected):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="ai_provider_error") from None
    except service.AIEmptyResponse:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="ai_empty_response") from None
    return TranslateResponse(
        hints=[HintOut(text=h) for h in result.hints],
        model=result.model,
        latency_ms=result.latency_ms,
    )
```

`main.py`: add `from flinq.api.ai import router as ai_router` (keep the import block alphabetized) and `app.include_router(ai_router)` after `dictionary_router`.

- [ ] **Step 4: Run to verify pass** (5 tests), then the full suite once

- [ ] **Step 5: Gates + commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
git add backend/src/flinq/modules/ai_translation/schemas.py backend/src/flinq/api/ai.py backend/src/flinq/main.py backend/tests/api/test_ai_translate.py
git commit -m "feat(FLQ-3.5): add POST /api/ai/translate endpoint" -- backend/src/flinq/modules/ai_translation/schemas.py backend/src/flinq/api/ai.py backend/src/flinq/main.py backend/tests/api/test_ai_translate.py
```

---

### Task 6: Finalization

**Files:**
- Modify: `.superpowers/specs/2026-07-04-ai-translation-gateway-design.md` (status header; reconcile drift)
- Modify (via backlog MCP): FLQ-3 ACs + status

- [ ] **Step 1: Full gate run** (`uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest` — all green)

- [ ] **Step 2: Reconcile spec + commit**

```bash
git add .superpowers/specs/2026-07-04-ai-translation-gateway-design.md
git commit -m "docs(FLQ-3): reconcile design spec with implementation" -- .superpowers/specs/2026-07-04-ai-translation-gateway-design.md
```

- [ ] **Step 3: Backlog: check AC #1–#5, status Done, final summary (task_edit).**

- [ ] **Step 4: PR + squash-merge**

Push, PR to `main` titled `feat(FLQ-3): AI translation gateway`, wait CI green, squash-merge with a manually written message per AGENTS.md: subject `feat(FLQ-3): add AI translation gateway with contextual hints (#N)`, body explaining *why* (contextual AI hints for the Word Card, kill-switch, privacy-first audit), no branch names, no commit lists, no Co-authored-by. Delete the branch after merge.

---

## Self-Review (done at plan-writing time)

- **Spec coverage:** API contract (incl. all error rows) → Task 5; Decision 1 (hints/parsing) → Task 1; Decision 2 (prompt/normalization) → Task 1; Decision 3 (provider/retries/no-auth-header) → Task 3; Decision 4 (orchestration/audit/kill-switch) → Task 4; Decision 5 (`ai_requests`/migration/no-FK lesson_id/user cascade) → Task 2; Decision 6 (error mapping) → Task 5; privacy regression test → Task 4; both spec Deviations respected (no cache anywhere; no lesson-table reads anywhere). No gaps found.
- **Placeholder scan:** clean — every code step carries complete code; migration step mirrors an existing sibling file 1:1 by instruction with the two revision constants given.
- **Type consistency:** `LLMCompletion`/`LLMProvider` (T3) match FakeProvider usage (T4) and `_GoodProvider` (T5); `translate_hints` signature identical in T4 definition and T5 call; exceptions `AIDisabled`/`AIEmptyResponse`/`ProviderUnavailable`/`ProviderRejected` used consistently across T4/T5; `_default_provider` name matches the monkeypatch target in T5.
- **Risk notes for the implementer:** (1) `monkeypatch.setattr(get_settings(), "llm_enabled", ...)` mutates the lru_cache'd Settings instance — monkeypatch restores it automatically; do not `cache_clear()`. (2) The autouse `_no_backoff` fixture in T3 keeps retry tests fast — don't drop it. (3) `Settings(**base)` in T3 ignores `.env` only partially — it still reads env vars; the explicit kwargs win, which is what the tests rely on.
