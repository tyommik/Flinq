# Auth & Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end happy path — пользователь регистрируется → проходит onboarding → попадает на пустую `/learn/:lang/library` → создаёт урок из текста → видит карточку.

**Architecture:** Modular monolith (FastAPI + SQLAlchemy 2 async + Alembic + Taskiq + Redis для rate-limit) с identity-модулем, минимальным lessons-модулем (только текстовый импорт без worker pipeline) и React 19 + TanStack Router + shadcn/ui SPA. Сессии cookie-based в Postgres (ADR-0008), URL-схема `/learn/:lang/...` (ADR-0007), tokens по ADR-0009.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy 2 async / Alembic / asyncpg / argon2-cffi / Redis / pytest+testcontainers / pyright. React 19 / TypeScript / Vite / TanStack Router+Query / Zustand / Tailwind v4 / shadcn/ui / Vitest.

**Связано с:** ADR-0006/0007/0008/0009, `docs/architecture/2026-04-11-mvp-domain-model.md`, `docs/ui/{login,register,onboarding,library,word_card}.md`.

---

## Phases

| Phase | Что произведёт | Можно ли параллелить |
|---|---|---|
| 1. Backend identity foundation (Tasks 1–7) | Миграции, модели, password hash, сессии, middleware. `pytest` зелёный, нет endpoints. | Backend solo |
| 2. Auth & onboarding endpoints (Tasks 8–16) | Все `/auth/*`, `/me`, `/me/onboarding`, CLI bootstrap. curl-able API. | Backend solo, можно начать UI после Task 12 |
| 3. Frontend auth UI (Tasks 17–22) | shadcn init, AppTopBar, LanguagePicker, login/register/onboarding routes, protected route guard. Manual flow работает. | Можно стартовать параллельно после Task 12 |
| 4. Lessons API + Library page (Tasks 23–29) | Минимальные `/api/lessons` + Library page (FilterRow + SubTabs + LessonCard + Import modal). Полный DoD. | Backend (23–25) и Frontend (26–29) частично параллелятся |

## File structure (создаётся / меняется)

**Backend:**
```
backend/
├── alembic.ini                                    [unchanged]
├── migrations/
│   ├── env.py                                     [modify: add identity + lessons imports]
│   └── versions/
│       ├── 0001_identity.py                       [new]
│       └── 0002_lessons_minimal.py                [new]
└── src/flinq/
    ├── core/
    │   ├── security.py                            [new — password, csrf, session token]
    │   └── rate_limit.py                          [new — Redis-based]
    ├── api/
    │   ├── auth.py                                [new — /auth/* router]
    │   ├── me.py                                  [new — /me router]
    │   └── lessons.py                             [new — /api/lessons router]
    ├── modules/
    │   ├── identity/
    │   │   ├── __init__.py                        [new]
    │   │   ├── models.py                          [new — SQLAlchemy models]
    │   │   ├── schemas.py                         [new — Pydantic DTOs]
    │   │   ├── repo.py                            [new — User/Session repos]
    │   │   ├── service.py                         [new — register/login/logout/me/onboarding]
    │   │   └── middleware.py                      [new — session + CSRF]
    │   └── lesson_library/
    │       ├── __init__.py                        [new]
    │       ├── models.py                          [new]
    │       ├── schemas.py                         [new]
    │       ├── repo.py                            [new]
    │       └── service.py                         [new]
    ├── cli/
    │   └── identity.py                            [new — create-admin/reset-password/promote]
    ├── main.py                                    [modify: register routers + middleware]
    └── core/config.py                             [modify: add auth-related settings]
```

**Frontend:**
```
frontend/src/
├── styles/globals.css                             [done in ADR-0009 PR]
├── lib/
│   ├── utils.ts                                   [new — cn() helper]
│   └── api.ts                                     [new — fetch wrapper, CSRF token]
├── api/
│   ├── client.ts                                  [modify]
│   ├── auth.ts                                    [new]
│   ├── me.ts                                      [new]
│   └── lessons.ts                                 [new]
├── components/
│   ├── ui/                                        [new — shadcn outputs]
│   ├── AppTopBar.tsx                              [new]
│   ├── LanguagePicker.tsx                         [new]
│   ├── AvatarMenu.tsx                             [new]
│   └── ProtectedRoute.tsx                         [new]
├── features/
│   ├── auth/
│   │   ├── LoginForm.tsx                          [new]
│   │   └── RegisterForm.tsx                       [new]
│   ├── onboarding/
│   │   └── OnboardingForm.tsx                     [new]
│   └── library/
│       ├── LibraryPage.tsx                        [new]
│       ├── FilterRow.tsx                          [new]
│       ├── SubTabs.tsx                            [new]
│       ├── LessonCarousel.tsx                     [new]
│       ├── LessonCard.tsx                         [new]
│       ├── LessonCover.tsx                        [new]
│       └── ImportLessonDialog.tsx                 [new]
├── stores/
│   └── userStore.ts                               [new — Zustand for current user + lang]
├── routes/                                        [refactor — TanStack Router tree]
│   ├── __root.tsx                                 [modify]
│   ├── login.tsx                                  [new]
│   ├── register.tsx                               [new]
│   ├── onboarding.tsx                             [new]
│   ├── learn.$lang.tsx                            [new — language layout]
│   ├── learn.$lang.library.tsx                    [new]
│   └── index.tsx                                  [modify — redirect logic]
└── routeTree.ts                                   [modify]
```

---

## Phase 1 — Backend Identity Foundation

### Task 1: Migration `0001_identity` + identity module skeleton

**Files:**
- Create: `backend/src/flinq/modules/identity/__init__.py`
- Create: `backend/src/flinq/modules/identity/models.py`
- Create: `backend/migrations/versions/0001_identity.py`
- Modify: `backend/migrations/env.py:21-22` (uncomment identity import)

- [ ] **Models** (`models.py`):

```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flinq.core.db import Base


UserRole = Literal["learner", "admin"]


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(16), nullable=False, default="learner")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False)
    settings: Mapped["UserSettings"] = relationship(back_populates="user", uselist=False)
    learning_languages: Mapped[list["UserLearningLanguage"]] = relationship(back_populates="user")
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user")

    __table_args__ = (
        CheckConstraint("role IN ('learner', 'admin')", name="users_role_check"),
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    native_language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    ui_language_code: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="profile")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    preferred_translation_language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_learning_language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reader_view_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="page")
    audio_speed: Mapped[float] = mapped_column(nullable=False, default=1.0)
    daily_goal_minutes: Mapped[int] = mapped_column(nullable=False, default=15)
    daily_goal_reviews: Mapped[int] = mapped_column(nullable=False, default=20)

    user: Mapped[User] = relationship(back_populates="settings")


class UserLearningLanguage(Base):
    __tablename__ = "user_learning_languages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    language_code: Mapped[str] = mapped_column(String(8), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="learning_languages")

    __table_args__ = (
        UniqueConstraint("user_id", "language_code", name="user_learning_languages_unique"),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # base64url 256-bit
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")
```

- [ ] **`__init__.py`:**

```python
from flinq.modules.identity import models  # noqa: F401
```

- [ ] **`migrations/env.py`** — раскомментировать import:

```python
from flinq.modules.identity import models as _identity_models  # noqa: F401
```

- [ ] **Generate migration:**

```bash
cd backend
uv run alembic revision --autogenerate -m "identity tables"
mv migrations/versions/<generated>_identity_tables.py migrations/versions/0001_identity.py
```

Откорректировать имя файла и `revision` константу на `"0001_identity"`. Проверить: миграция содержит CREATE TABLE для `users`, `user_profiles`, `user_settings`, `user_learning_languages`, `user_sessions`.

- [ ] **Apply & verify:**

```bash
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```

Expected: оба direction'а работают без ошибок.

- [ ] **Commit:**

```bash
git add backend/src/flinq/modules/identity backend/migrations
git commit -m "feat(identity): add SQLAlchemy models and 0001 migration"
```

---

### Task 2: Password hashing (`core/security.py` part 1)

**Files:**
- Create: `backend/src/flinq/core/security.py`
- Create: `backend/tests/core/test_security.py`

- [ ] **Test** (`backend/tests/core/test_security.py`):

```python
from flinq.core.security import hash_password, verify_password


def test_hash_and_verify_round_trip() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong password", h) is False


def test_hash_is_unique_per_call() -> None:
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2  # argon2 uses random salt
    assert verify_password("same", h1) is True
    assert verify_password("same", h2) is True


def test_verify_rejects_invalid_hash() -> None:
    assert verify_password("anything", "$argon2id$invalid") is False
```

- [ ] **Run failing test:**

```bash
cd backend
uv run pytest tests/core/test_security.py -v
```

Expected: ImportError (module not yet created).

- [ ] **Implementation** (`core/security.py`):

```python
"""Cryptographic utilities: password hashing, session tokens, CSRF tokens.

See ADR-0008 for parameter rationale.
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    """argon2id hash with random salt."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time verify. False on any failure (mismatch or malformed hash)."""
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_session_token() -> str:
    """256-bit random, base64url, no padding. Used as user_sessions.id."""
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    """128-bit random, base64url. Used in double-submit cookie."""
    return secrets.token_urlsafe(16)
```

- [ ] **Run passing test:**

```bash
uv run pytest tests/core/test_security.py -v
```

Expected: 3 PASSED.

- [ ] **Commit:**

```bash
git add backend/src/flinq/core/security.py backend/tests/core/test_security.py
git commit -m "feat(core): add argon2 password hashing and token generators"
```

---

### Task 3: Identity repo

**Files:**
- Create: `backend/src/flinq/modules/identity/repo.py`
- Create: `backend/tests/modules/identity/test_repo.py`
- Create: `backend/tests/modules/identity/__init__.py` (empty)

- [ ] **Test:**

```python
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.identity.repo import UserRepo, SessionRepo


@pytest.mark.asyncio
async def test_create_user_with_profile_and_settings(db_session: AsyncSession) -> None:
    repo = UserRepo(db_session)
    user = await repo.create(email="alice@example.com", password_hash="hash", display_name="Alice")
    assert user.id is not None
    assert user.email == "alice@example.com"
    assert user.role == "learner"
    assert user.profile.display_name == "Alice"
    assert user.settings is not None


@pytest.mark.asyncio
async def test_get_by_email_case_insensitive(db_session: AsyncSession) -> None:
    repo = UserRepo(db_session)
    await repo.create(email="bob@example.com", password_hash="h", display_name="Bob")
    user = await repo.get_by_email("BOB@example.com")
    assert user is not None and user.email == "bob@example.com"


@pytest.mark.asyncio
async def test_email_uniqueness(db_session: AsyncSession) -> None:
    repo = UserRepo(db_session)
    await repo.create(email="x@x.com", password_hash="h", display_name="X")
    with pytest.raises(Exception):
        await repo.create(email="x@x.com", password_hash="h", display_name="X2")


@pytest.mark.asyncio
async def test_session_create_and_lookup(db_session: AsyncSession) -> None:
    user_repo = UserRepo(db_session)
    user = await user_repo.create(email="s@s.com", password_hash="h", display_name="S")
    sess_repo = SessionRepo(db_session)
    sess = await sess_repo.create(
        token="abc",
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        user_agent="test",
        ip_hash="hashed-ip",
    )
    found = await sess_repo.get_active("abc")
    assert found is not None and found.user_id == user.id


@pytest.mark.asyncio
async def test_session_expired_returns_none(db_session: AsyncSession) -> None:
    user_repo = UserRepo(db_session)
    user = await user_repo.create(email="exp@x.com", password_hash="h", display_name="E")
    sess_repo = SessionRepo(db_session)
    await sess_repo.create(
        token="expired",
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert await sess_repo.get_active("expired") is None
```

- [ ] **Implementation** (`modules/identity/repo.py`):

```python
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flinq.modules.identity.models import (
    User, UserProfile, UserSettings, UserSession, UserLearningLanguage,
)


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, email: str, password_hash: str, display_name: str, role: str = "learner",
    ) -> User:
        user = User(
            email=email.lower().strip(),
            password_hash=password_hash,
            role=role,
        )
        user.profile = UserProfile(display_name=display_name)
        user.settings = UserSettings()
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.lower().strip())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def mark_onboarded(self, user_id: uuid.UUID, when: datetime) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(onboarded_at=when)
        )

    async def hard_delete(self, user_id: uuid.UUID) -> None:
        user = await self.session.get(User, user_id)
        if user is not None:
            await self.session.delete(user)


class SessionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, token: str, user_id: uuid.UUID, expires_at: datetime,
        user_agent: str | None = None, ip_hash: str | None = None,
    ) -> UserSession:
        sess = UserSession(
            id=token, user_id=user_id, expires_at=expires_at,
            user_agent=user_agent, ip_hash=ip_hash,
        )
        self.session.add(sess)
        await self.session.flush()
        return sess

    async def get_active(self, token: str) -> UserSession | None:
        stmt = select(UserSession).where(
            UserSession.id == token,
            UserSession.expires_at > func.now(),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def touch(self, token: str, *, new_expires_at: datetime) -> None:
        await self.session.execute(
            update(UserSession)
            .where(UserSession.id == token)
            .values(last_seen_at=func.now(), expires_at=new_expires_at)
        )

    async def invalidate(self, token: str) -> None:
        await self.session.execute(
            update(UserSession).where(UserSession.id == token).values(expires_at=func.now())
        )

    async def cleanup_expired(self) -> int:
        result = await self.session.execute(
            UserSession.__table__.delete().where(UserSession.expires_at < func.now())
        )
        return result.rowcount or 0
```

- [ ] **conftest** support — обновить `backend/tests/conftest.py`:

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

from flinq.core.config import get_settings
from flinq.core.db import Base, init_engine, dispose_engine, session_scope


@pytest_asyncio.fixture(scope="session")
async def pg_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest_asyncio.fixture(scope="session", autouse=True)
async def db_setup(pg_container, monkeypatch_session):
    url = pg_container.get_connection_url().replace("psycopg2", "asyncpg")
    monkeypatch_session.setenv("FLINQ_DATABASE_URL", url)
    get_settings.cache_clear()
    settings = get_settings()
    engine = init_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with session_scope() as s:
        yield s


@pytest.fixture(scope="session")
def monkeypatch_session():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()
```

- [ ] **Run tests:**

```bash
uv run pytest tests/modules/identity/test_repo.py -v
```

Expected: 5 PASSED.

- [ ] **Commit:**

```bash
git add backend/src/flinq/modules/identity/repo.py backend/tests
git commit -m "feat(identity): add UserRepo and SessionRepo with tests"
```

---

### Task 4: Rate limit (Redis-based)

**Files:**
- Create: `backend/src/flinq/core/rate_limit.py`
- Create: `backend/tests/core/test_rate_limit.py`

- [ ] **Test:**

```python
import pytest
from flinq.core.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_first_n_requests_allowed(redis_client) -> None:
    rl = RateLimiter(redis_client, max_attempts=5, window_seconds=900)
    for _ in range(5):
        assert await rl.check_and_increment("login:1.2.3.4:user@x") is True


@pytest.mark.asyncio
async def test_n_plus_one_blocked(redis_client) -> None:
    rl = RateLimiter(redis_client, max_attempts=3, window_seconds=900)
    for _ in range(3):
        await rl.check_and_increment("login:k1")
    assert await rl.check_and_increment("login:k1") is False


@pytest.mark.asyncio
async def test_reset(redis_client) -> None:
    rl = RateLimiter(redis_client, max_attempts=3, window_seconds=900)
    await rl.check_and_increment("login:k2")
    await rl.reset("login:k2")
    for _ in range(3):
        assert await rl.check_and_increment("login:k2") is True
```

- [ ] **Implementation:**

```python
"""Redis-backed rate limiter for auth endpoints (ADR-0008)."""

from __future__ import annotations

from redis.asyncio import Redis


class RateLimiter:
    def __init__(self, redis: Redis, *, max_attempts: int, window_seconds: int) -> None:
        self.redis = redis
        self.max = max_attempts
        self.window = window_seconds

    async def check_and_increment(self, key: str) -> bool:
        """Return True if under limit (and increment), False if over."""
        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, self.window)
        return current <= self.max

    async def reset(self, key: str) -> None:
        await self.redis.delete(key)

    async def get_retry_after(self, key: str) -> int:
        ttl = await self.redis.ttl(key)
        return max(ttl, 0)
```

- [ ] **conftest** — добавить `redis_client` fixture аналогично `pg_container` (через `RedisContainer` из testcontainers).

- [ ] **Run tests, commit:**

```bash
uv run pytest tests/core/test_rate_limit.py -v
git add backend/src/flinq/core/rate_limit.py backend/tests/core/test_rate_limit.py
git commit -m "feat(core): add Redis rate limiter"
```

---

### Task 5: Session middleware

**Files:**
- Create: `backend/src/flinq/modules/identity/middleware.py`
- Create: `backend/tests/modules/identity/test_middleware.py`

- [ ] **Implementation** (`middleware.py`):

```python
"""Session and CSRF middleware (ADR-0008).

Reads session cookie, hydrates `request.state.user_id` and `request.state.session_token`.
For mutating methods, validates `X-CSRF-Token` header against `flinq_csrf` cookie.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from fastapi import HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from flinq.core.db import session_scope
from flinq.modules.identity.repo import SessionRepo

SESSION_COOKIE = "flinq_session"
CSRF_COOKIE = "flinq_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL = timedelta(days=30)
TOUCH_INTERVAL = timedelta(minutes=5)
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_PATHS = {"/health", "/auth/register", "/auth/login"}


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.user_id = None
        request.state.session_token = None

        token = request.cookies.get(SESSION_COOKIE)
        if token:
            async with session_scope() as s:
                sess = await SessionRepo(s).get_active(token)
                if sess is not None:
                    request.state.user_id = sess.user_id
                    request.state.session_token = token
                    if datetime.now(timezone.utc) - sess.last_seen_at.replace(
                        tzinfo=timezone.utc
                    ) > TOUCH_INTERVAL:
                        await SessionRepo(s).touch(
                            token, new_expires_at=datetime.now(timezone.utc) + SESSION_TTL,
                        )

        return await call_next(request)


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if (
            request.method in MUTATING_METHODS
            and request.url.path not in PUBLIC_PATHS
        ):
            cookie = request.cookies.get(CSRF_COOKIE)
            header = request.headers.get(CSRF_HEADER)
            if not cookie or cookie != header:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch"
                )
        return await call_next(request)
```

- [ ] **Wire up in `main.py`:**

```python
# backend/src/flinq/main.py
from flinq.modules.identity.middleware import SessionMiddleware, CSRFMiddleware
# ...
app.add_middleware(CSRFMiddleware)
app.add_middleware(SessionMiddleware)
```

- [ ] **Test:** интеграционный тест через `httpx.AsyncClient`. Покрыть: (a) валидный cookie → state установлен; (b) невалидный → state None; (c) POST без CSRF → 403; (d) GET без CSRF → ok.

- [ ] **Commit:**

```bash
git add backend/src/flinq/modules/identity/middleware.py backend/src/flinq/main.py backend/tests
git commit -m "feat(identity): add session and CSRF middleware"
```

---

### Task 6: Settings extension

**Files:**
- Modify: `backend/src/flinq/core/config.py`

- [ ] Добавить в `Settings`:

```python
# Auth (ADR-0008)
allow_public_registration: bool = True
initial_admin_email: str = ""
session_ttl_seconds: int = 30 * 24 * 3600  # 30 days
login_max_attempts: int = 5
login_window_seconds: int = 15 * 60
register_max_attempts: int = 10
register_window_seconds: int = 3600
```

- [ ] **Commit:**

```bash
git add backend/src/flinq/core/config.py
git commit -m "feat(config): add auth-related settings"
```

---

### Task 7: Cleanup-expired-sessions worker job

**Files:**
- Create: `backend/src/flinq/worker/jobs/identity.py`

- [ ] **Implementation:**

```python
from datetime import timedelta

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from flinq.core.db import session_scope
from flinq.modules.identity.repo import SessionRepo
from flinq.worker.broker import broker


@broker.task(schedule=[{"cron": "0 3 * * *"}])  # daily 03:00
async def cleanup_expired_sessions() -> int:
    async with session_scope() as s:
        return await SessionRepo(s).cleanup_expired()


scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
```

- [ ] **Commit:**

```bash
git add backend/src/flinq/worker
git commit -m "feat(worker): add session cleanup job (daily)"
```

---

## Phase 2 — Auth & Onboarding Endpoints

### Task 8: Pydantic schemas

**Files:**
- Create: `backend/src/flinq/modules/identity/schemas.py`

- [ ] **Implementation:**

```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = True


class OnboardingRequest(BaseModel):
    ui_language: str = Field(pattern="^(en|ru)$")
    learning_languages: list[str] = Field(min_length=1)
    translation_language: str

    @field_validator("learning_languages")
    @classmethod
    def all_supported(cls, v: list[str]) -> list[str]:
        for code in v:
            if code not in {"en", "ru", "pt"}:
                raise ValueError(f"unsupported language: {code}")
        return v


class DeleteMeRequest(BaseModel):
    password: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: Literal["learner", "admin"]
    display_name: str
    ui_language_code: str
    learning_languages: list[str]
    last_learning_language_code: str | None
    needs_onboarding: bool
    onboarded_at: datetime | None
```

- [ ] **Commit:**

```bash
git add backend/src/flinq/modules/identity/schemas.py
git commit -m "feat(identity): add Pydantic schemas"
```

---

### Task 9: `POST /auth/register`

**Files:**
- Create: `backend/src/flinq/modules/identity/service.py`
- Create: `backend/src/flinq/api/auth.py`
- Modify: `backend/src/flinq/main.py` (register router)

- [ ] **Service** (`service.py`):

```python
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError

from flinq.core.config import get_settings
from flinq.core.security import (
    generate_csrf_token, generate_session_token, hash_password, verify_password,
)
from flinq.modules.identity.middleware import (
    CSRF_COOKIE, SESSION_COOKIE, SESSION_TTL,
)
from flinq.modules.identity.models import User
from flinq.modules.identity.repo import SessionRepo, UserRepo


def _hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(ip.encode()).hexdigest()[:64]


def _set_session_cookies(
    response: Response, *, session_token: str, csrf_token: str, persistent: bool,
) -> None:
    max_age = SESSION_TTL.total_seconds() if persistent else None
    kwargs = {"max_age": int(max_age)} if max_age is not None else {}
    response.set_cookie(
        SESSION_COOKIE, session_token, httponly=True, secure=True, samesite="lax", **kwargs
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, httponly=False, secure=True, samesite="lax", **kwargs
    )


async def register_user(
    request: Request, response: Response, *,
    display_name: str, email: str, password: str,
    user_repo: UserRepo, session_repo: SessionRepo,
) -> User:
    settings = get_settings()
    if not settings.allow_public_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")

    role = "admin" if email.lower() == settings.initial_admin_email.lower() else "learner"

    try:
        user = await user_repo.create(
            email=email, password_hash=hash_password(password), display_name=display_name, role=role,
        )
    except IntegrityError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use") from e

    token = generate_session_token()
    csrf = generate_csrf_token()
    await session_repo.create(
        token=token,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + SESSION_TTL,
        user_agent=request.headers.get("user-agent"),
        ip_hash=_hash_ip(request.client.host if request.client else None),
    )
    _set_session_cookies(response, session_token=token, csrf_token=csrf, persistent=True)
    return user
```

- [ ] **Router** (`api/auth.py`):

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from flinq.core.db import get_session
from flinq.modules.identity import service
from flinq.modules.identity.repo import SessionRepo, UserRepo
from flinq.modules.identity.schemas import RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest, request: Request, response: Response,
    session=Depends(get_session),
) -> dict:
    user_repo = UserRepo(session)
    session_repo = SessionRepo(session)
    user = await service.register_user(
        request, response,
        display_name=body.display_name, email=body.email, password=body.password,
        user_repo=user_repo, session_repo=session_repo,
    )
    return {"id": str(user.id), "needs_onboarding": True}
```

- [ ] **Test** (`tests/api/test_auth_register.py`):

```python
import pytest
from httpx import ASGITransport, AsyncClient

from flinq.main import create_app


@pytest.mark.asyncio
async def test_register_success() -> None:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        r = await c.post("/auth/register", json={
            "display_name": "Alice", "email": "a@x.com", "password": "abcdefghij"
        })
        assert r.status_code == 201
        assert r.cookies.get("flinq_session")
        assert r.cookies.get("flinq_csrf")


@pytest.mark.asyncio
async def test_register_duplicate_email_409() -> None:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        await c.post("/auth/register", json={
            "display_name": "B", "email": "b@x.com", "password": "abcdefghij",
        })
        r = await c.post("/auth/register", json={
            "display_name": "B2", "email": "b@x.com", "password": "abcdefghij",
        })
        assert r.status_code == 409
```

- [ ] **Run, commit:**

```bash
uv run pytest tests/api/test_auth_register.py -v
git add backend/src/flinq/{api,modules,main}.py backend/tests
git commit -m "feat(auth): POST /auth/register with auto-login session"
```

---

### Task 10: `POST /auth/login` + rate limit

**Files:**
- Modify: `backend/src/flinq/modules/identity/service.py`
- Modify: `backend/src/flinq/api/auth.py`

- [ ] **Service** (добавить):

```python
async def login_user(
    request: Request, response: Response, *,
    email: str, password: str, remember_me: bool,
    user_repo: UserRepo, session_repo: SessionRepo, rate_limiter: RateLimiter,
) -> User:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    rl_key = f"login:{ip}:{email.lower()}"

    if not await rate_limiter.check_and_increment(rl_key):
        retry_after = await rate_limiter.get_retry_after(rl_key)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Retry in {retry_after // 60} min",
            headers={"Retry-After": str(retry_after)},
        )

    user = await user_repo.get_by_email(email)
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    await rate_limiter.reset(rl_key)

    token = generate_session_token()
    csrf = generate_csrf_token()
    await session_repo.create(
        token=token, user_id=user.id,
        expires_at=datetime.now(timezone.utc) + SESSION_TTL,
        user_agent=request.headers.get("user-agent"),
        ip_hash=_hash_ip(ip),
    )
    _set_session_cookies(response, session_token=token, csrf_token=csrf, persistent=remember_me)
    return user
```

- [ ] **Router** (добавить endpoint):

```python
@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response,
    session=Depends(get_session), redis=Depends(get_redis),
) -> dict:
    rl = RateLimiter(redis, max_attempts=settings.login_max_attempts, window_seconds=settings.login_window_seconds)
    user = await service.login_user(
        request, response,
        email=body.email, password=body.password, remember_me=body.remember_me,
        user_repo=UserRepo(session), session_repo=SessionRepo(session), rate_limiter=rl,
    )
    return {"id": str(user.id), "needs_onboarding": user.onboarded_at is None}
```

(потребуется зависимость `get_redis()` — добавить в `core/db.py` или новый `core/redis.py` с `redis.asyncio.Redis.from_url(settings.redis_url)`).

- [ ] **Tests:** success, wrong password 401, rate limit 429 после 5 неудач.

- [ ] **Commit:**

```bash
git commit -am "feat(auth): POST /auth/login with rate limiting and remember_me"
```

---

### Task 11: `POST /auth/logout`

- [ ] **Implementation** (router):

```python
@router.post("/logout")
async def logout(request: Request, response: Response, session=Depends(get_session)) -> dict:
    token = request.state.session_token
    if token:
        await SessionRepo(session).invalidate(token)
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return {"ok": True}
```

- [ ] **Test:** login → logout → cookie cleared, повторный API-call с тем же token = 401.

- [ ] **Commit:** `feat(auth): POST /auth/logout`

---

### Task 12: `GET /me`

**Files:**
- Create: `backend/src/flinq/api/me.py`

- [ ] **Implementation:**

```python
from fastapi import APIRouter, Depends, HTTPException, Request, status

from flinq.core.db import get_session
from flinq.modules.identity.repo import UserRepo
from flinq.modules.identity.schemas import MeResponse

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeResponse)
async def get_me(request: Request, session=Depends(get_session)) -> MeResponse:
    if request.state.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    user = await UserRepo(session).get_by_id(request.state.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    return MeResponse(
        id=user.id, email=user.email, role=user.role,
        display_name=user.profile.display_name,
        ui_language_code=user.profile.ui_language_code,
        learning_languages=[ll.language_code for ll in user.learning_languages],
        last_learning_language_code=user.settings.last_learning_language_code,
        needs_onboarding=user.onboarded_at is None,
        onboarded_at=user.onboarded_at,
    )
```

- [ ] **Test, commit:** `feat(me): GET /me with auth`

---

### Task 13: `POST /me/onboarding`

- [ ] **Service:**

```python
async def complete_onboarding(
    user_id: uuid.UUID, *,
    ui_language: str, learning_languages: list[str], translation_language: str,
    user_repo: UserRepo, session: AsyncSession,
) -> None:
    user = await user_repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    user.profile.ui_language_code = ui_language
    user.settings.preferred_translation_language_code = translation_language
    user.settings.last_learning_language_code = learning_languages[0]

    existing = {ll.language_code for ll in user.learning_languages}
    for code in learning_languages:
        if code not in existing:
            session.add(UserLearningLanguage(user_id=user_id, language_code=code))

    await user_repo.mark_onboarded(user_id, datetime.now(timezone.utc))
```

- [ ] **Router** (в `api/me.py`):

```python
@router.post("/onboarding")
async def post_onboarding(
    body: OnboardingRequest, request: Request, session=Depends(get_session),
) -> dict:
    if request.state.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    await service.complete_onboarding(
        request.state.user_id,
        ui_language=body.ui_language,
        learning_languages=body.learning_languages,
        translation_language=body.translation_language,
        user_repo=UserRepo(session), session=session,
    )
    return {"ok": True, "redirect": f"/learn/{body.learning_languages[0]}/library"}
```

- [ ] **Test, commit:** `feat(me): POST /me/onboarding`

---

### Task 14: `DELETE /me` (account deletion)

- [ ] **Router:**

```python
@router.delete("")
async def delete_me(
    body: DeleteMeRequest, request: Request, response: Response, session=Depends(get_session),
) -> dict:
    if request.state.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    user = await UserRepo(session).get_by_id(request.state.user_id)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid password")
    await UserRepo(session).hard_delete(user.id)
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return {"ok": True}
```

- [ ] **Test:** delete + verify by re-login 401. **Commit:** `feat(me): DELETE /me with password confirmation`

---

### Task 15: CLI bootstrap

**Files:**
- Create: `backend/src/flinq/cli/identity.py`
- Modify: `backend/src/flinq/cli/main.py` (register subcommands)

- [ ] **CLI:**

```python
# cli/identity.py
import asyncio
import secrets
import typer

from flinq.core.db import init_engine, dispose_engine, session_scope
from flinq.core.config import get_settings
from flinq.core.security import hash_password
from flinq.modules.identity.repo import UserRepo

app = typer.Typer(help="Identity management commands.")


async def _run(coro):
    settings = get_settings()
    init_engine(settings)
    try:
        return await coro
    finally:
        await dispose_engine()


@app.command("create-admin")
def create_admin(email: str = typer.Argument(...), name: str = typer.Option("Admin")) -> None:
    """Create a new admin user with a random password printed to stdout."""
    async def _do():
        async with session_scope() as s:
            repo = UserRepo(s)
            if await repo.get_by_email(email):
                typer.echo(f"User {email} already exists", err=True)
                raise typer.Exit(1)
            password = secrets.token_urlsafe(12)
            await repo.create(email=email, password_hash=hash_password(password),
                              display_name=name, role="admin")
            typer.echo(f"Created admin {email} with password: {password}")
    asyncio.run(_run(_do()))


@app.command("reset-password")
def reset_password(email: str = typer.Argument(...)) -> None:
    """Reset password to a random temporary value, printed to stdout."""
    async def _do():
        async with session_scope() as s:
            repo = UserRepo(s)
            user = await repo.get_by_email(email)
            if user is None:
                typer.echo(f"User {email} not found", err=True)
                raise typer.Exit(1)
            password = secrets.token_urlsafe(12)
            user.password_hash = hash_password(password)
            typer.echo(f"New password for {email}: {password}")
    asyncio.run(_run(_do()))


@app.command("promote")
def promote(email: str = typer.Argument(...)) -> None:
    async def _do():
        async with session_scope() as s:
            user = await UserRepo(s).get_by_email(email)
            if user is None:
                typer.echo("Not found", err=True); raise typer.Exit(1)
            user.role = "admin"
            typer.echo(f"Promoted {email} to admin")
    asyncio.run(_run(_do()))
```

- [ ] **Wire-up** (`cli/main.py`):

```python
from flinq.cli.identity import app as identity_app
app.add_typer(identity_app, name="identity")
```

- [ ] **Manual smoke test:**

```bash
docker compose up -d postgres
uv run alembic upgrade head
uv run flinq identity create-admin admin@example.com
```

- [ ] **Commit:** `feat(cli): add identity commands (create-admin, reset-password, promote)`

---

### Task 16: API integration smoke test

- [ ] Создать `backend/tests/integration/test_auth_flow.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from flinq.main import create_app


@pytest.mark.asyncio
async def test_full_auth_onboarding_flow() -> None:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        # Register
        r = await c.post("/auth/register", json={
            "display_name": "X", "email": "x@x.com", "password": "abcdefghij",
        })
        assert r.status_code == 201
        csrf = r.cookies["flinq_csrf"]

        # /me — needs_onboarding == True
        r = await c.get("/me")
        assert r.json()["needs_onboarding"] is True

        # Complete onboarding
        r = await c.post("/me/onboarding",
            json={"ui_language": "ru", "learning_languages": ["pt"], "translation_language": "ru"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.json()["redirect"] == "/learn/pt/library"

        # /me — onboarded
        r = await c.get("/me")
        assert r.json()["needs_onboarding"] is False
        assert r.json()["last_learning_language_code"] == "pt"

        # Logout
        r = await c.post("/auth/logout", headers={"X-CSRF-Token": csrf})
        r = await c.get("/me")
        assert r.status_code == 401
```

- [ ] Запустить, исправить найденные баги, **commit**: `test(integration): full auth+onboarding flow`

> ✅ Phase 2 done. API curl-able.

---

## Phase 3 — Frontend Auth UI

### Task 17: shadcn init + Inter font

- [ ] **Init shadcn:**

```bash
cd frontend
corepack pnpm dlx shadcn@latest init
```

Ответы: TypeScript yes, Tailwind v4 yes, default style, base color neutral, CSS variables yes, alias `@/components`, `@/lib/utils`, components.json в корне frontend/.

Проверить, что `components.json` создан, `src/lib/utils.ts` содержит `cn()`.

- [ ] **Add font** в `frontend/index.html` (HEAD):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
```

- [ ] **Add base components:**

```bash
corepack pnpm dlx shadcn@latest add button input label form checkbox dialog dropdown-menu select toast
```

- [ ] **Commit:**

```bash
git add frontend/components.json frontend/src/components/ui frontend/src/lib frontend/index.html
git commit -m "feat(frontend): init shadcn/ui and add base components"
```

---

### Task 18: API client + user store + types

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/api/auth.ts`, `frontend/src/api/me.ts`
- Create: `frontend/src/stores/userStore.ts`

- [ ] **`api/client.ts`:**

```typescript
const API_BASE = '/api'  // FastAPI mounted at root in dev, proxied via Vite

function getCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp('(^|;\\s*)' + name + '=([^;]+)'))
  return m ? decodeURIComponent(m[2]) : null
}

export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(detail) }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.method && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(init.method)) {
    const csrf = getCookie('flinq_csrf')
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  const r = await fetch(path.startsWith('http') ? path : path, { ...init, headers, credentials: 'include' })
  if (!r.ok) {
    const detail = await r.json().catch(() => ({ detail: r.statusText }))
    throw new ApiError(r.status, detail.detail || r.statusText)
  }
  return r.status === 204 ? (undefined as T) : r.json()
}
```

- [ ] **`api/auth.ts`:**

```typescript
import { api } from './client'

export type RegisterPayload = { display_name: string; email: string; password: string }
export type LoginPayload = { email: string; password: string; remember_me: boolean }

export const authApi = {
  register: (p: RegisterPayload) => api<{ id: string; needs_onboarding: boolean }>('/auth/register', {
    method: 'POST', body: JSON.stringify(p),
  }),
  login: (p: LoginPayload) => api<{ id: string; needs_onboarding: boolean }>('/auth/login', {
    method: 'POST', body: JSON.stringify(p),
  }),
  logout: () => api<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
}
```

- [ ] **`api/me.ts`:**

```typescript
import { api } from './client'

export type MeResponse = {
  id: string; email: string; role: 'learner' | 'admin'
  display_name: string; ui_language_code: string
  learning_languages: string[]; last_learning_language_code: string | null
  needs_onboarding: boolean; onboarded_at: string | null
}

export type OnboardingPayload = {
  ui_language: string; learning_languages: string[]; translation_language: string
}

export const meApi = {
  get: () => api<MeResponse>('/me'),
  onboarding: (p: OnboardingPayload) =>
    api<{ ok: boolean; redirect: string }>('/me/onboarding', { method: 'POST', body: JSON.stringify(p) }),
}
```

- [ ] **`stores/userStore.ts`:**

```typescript
import { create } from 'zustand'
import type { MeResponse } from '@/api/me'

type UserState = {
  user: MeResponse | null
  setUser: (u: MeResponse | null) => void
  currentLang: string | null  // derived from URL or last_learning_language_code
  setCurrentLang: (lang: string) => void
}

export const useUserStore = create<UserState>((set) => ({
  user: null,
  currentLang: null,
  setUser: (user) => set({ user, currentLang: user?.last_learning_language_code ?? null }),
  setCurrentLang: (lang) => set({ currentLang: lang }),
}))
```

- [ ] **Commit:** `feat(frontend): add API client, auth/me endpoints, user store`

---

### Task 19: Public route layout + login form

**Files:**
- Create: `frontend/src/features/auth/LoginForm.tsx`
- Create: `frontend/src/routes/login.tsx`
- Modify: `frontend/src/routeTree.ts`

- [ ] **`LoginForm.tsx`** (показано схематично, полный код пишется через shadcn `Form` + `useForm`):

```tsx
import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { authApi } from '@/api/auth'
import { meApi } from '@/api/me'
import { useUserStore } from '@/stores/userStore'

export function LoginForm() {
  const navigate = useNavigate()
  const setUser = useUserStore((s) => s.setUser)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true); setError(null)
    try {
      await authApi.login({ email, password, remember_me: remember })
      const me = await meApi.get()
      setUser(me)
      const lang = me.last_learning_language_code ?? me.learning_languages[0]
      navigate({ to: me.needs_onboarding ? '/onboarding' : `/learn/${lang}/library` })
    } catch (err: any) {
      setError(err.status === 429 ? 'Too many attempts. Try later.' : 'Invalid email or password')
    } finally { setSubmitting(false) }
  }

  return (
    <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4">
      <h1 className="text-3xl font-semibold text-center">Вход</h1>
      <div>
        <Label htmlFor="email">Электронная почта</Label>
        <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      <div>
        <Label htmlFor="password">Пароль</Label>
        <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={remember} onCheckedChange={(v) => setRemember(!!v)} />
        Запомнить меня
      </label>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button type="submit" className="w-full" disabled={submitting}>Вход</Button>
      <p className="text-sm text-center text-muted-foreground">
        Нет аккаунта? <a href="/register" className="text-primary">Зарегистрироваться</a>
      </p>
    </form>
  )
}
```

- [ ] **`routes/login.tsx`:**

```tsx
import { createRoute } from '@tanstack/react-router'
import { LoginForm } from '@/features/auth/LoginForm'
import { rootRoute } from './__root'

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: () => (
    <div className="min-h-screen flex items-center justify-center p-4 bg-background">
      <LoginForm />
    </div>
  ),
})
```

- [ ] Подключить в `routeTree.ts`. **Commit:** `feat(auth): add login form and route`

---

### Task 20: Register form + route

Аналогично Task 19. UX по `docs/ui/register.md`. Поля: display_name, email, password (min 10). После успеха → `/onboarding`.

- [ ] Создать `RegisterForm.tsx`, `routes/register.tsx`. **Commit:** `feat(auth): add register form and route`

---

### Task 21: Onboarding form + route

**Files:**
- Create: `frontend/src/features/onboarding/OnboardingForm.tsx`
- Create: `frontend/src/routes/onboarding.tsx`

- [ ] **`OnboardingForm.tsx`:**

```tsx
const LANGS = [
  { code: 'en', name: 'English' },
  { code: 'ru', name: 'Русский' },
  { code: 'pt', name: 'Português' },
]

// UI: Select для UI language, чекбоксы для learning, Select для translation.
// onSubmit → meApi.onboarding(...) → setUser(...) → navigate(redirect from response).
```

(Полный код по аналогии с LoginForm + `docs/ui/onboarding.md` §3.)

- [ ] **Commit:** `feat(onboarding): add form and route`

---

### Task 22: Protected route guard + `/` redirect

**Files:**
- Create: `frontend/src/components/ProtectedRoute.tsx`
- Modify: `frontend/src/routes/index.tsx` (root index → redirect logic)

- [ ] **`ProtectedRoute.tsx`:**

```tsx
import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { meApi } from '@/api/me'
import { useUserStore } from '@/stores/userStore'

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const setUser = useUserStore((s) => s.setUser)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['me'], queryFn: meApi.get, retry: false,
  })

  useEffect(() => {
    if (data) setUser(data)
    if (isError) navigate({ to: '/login' })
    if (data?.needs_onboarding) navigate({ to: '/onboarding' })
  }, [data, isError, setUser, navigate])

  if (isLoading) return <div className="min-h-screen flex items-center justify-center">Loading…</div>
  if (!data) return null
  return <>{children}</>
}
```

- [ ] **`routes/index.tsx`:**

```tsx
import { createRoute, redirect } from '@tanstack/react-router'
import { meApi } from '@/api/me'
import { rootRoute } from './__root'

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute, path: '/',
  beforeLoad: async () => {
    try {
      const me = await meApi.get()
      if (me.needs_onboarding) throw redirect({ to: '/onboarding' })
      const lang = me.last_learning_language_code ?? me.learning_languages[0]
      throw redirect({ to: `/learn/${lang}/library` })
    } catch {
      throw redirect({ to: '/login' })
    }
  },
  component: () => null,
})
```

- [ ] **Manual smoke test:** register → onboarding → `/learn/pt/library` (404 пока, нормально). Logout → `/login`.
- [ ] **Commit:** `feat(routing): add protected route guard and / redirect logic`

> ✅ Phase 3 done. Manual e2e flow up to library page works.

---

## Phase 4 — Lessons API + Library Page

### Task 23: Lessons migration + minimal model

**Files:**
- Create: `backend/src/flinq/modules/lesson_library/{models,repo,schemas,service}.py`
- Create: `backend/migrations/versions/0002_lessons_minimal.py`
- Modify: `backend/migrations/env.py`

- [ ] **`models.py`** (минимум — без segments/occurrences, они в следующем эпике):

```python
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from flinq.core.db import Base

LessonStatus = Literal["draft", "processing", "ready", "failed", "archived"]
LessonVisibility = Literal["private", "shared"]


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    language_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_text: Mapped[str] = mapped_column(nullable=False)  # full lesson text; segmentation в next epic
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visibility: Mapped[LessonVisibility] = mapped_column(String(16), nullable=False, default="private")
    status: Mapped[LessonStatus] = mapped_column(String(16), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
```

- [ ] Generate migration `0002_lessons_minimal.py`. Apply.
- [ ] **Commit:** `feat(lesson_library): add minimal Lesson model and 0002 migration`

---

### Task 24: `GET /api/lessons` (list)

**Files:**
- Create: `backend/src/flinq/api/lessons.py`
- Create: `backend/src/flinq/modules/lesson_library/repo.py`

- [ ] **Schemas:**

```python
class LessonSummary(BaseModel):
    id: uuid.UUID
    title: str
    language_code: str
    word_count: int
    visibility: str
    status: str
    created_at: datetime


class LessonListResponse(BaseModel):
    items: list[LessonSummary]
    total: int
    page: int
    page_size: int
```

- [ ] **Repo:**

```python
class LessonRepo:
    def __init__(self, session): self.session = session

    async def list_for_user(
        self, *, user_id: uuid.UUID, lang: str, q: str | None = None,
        visibility: str = "all", page: int = 1, page_size: int = 25,
    ) -> tuple[list[Lesson], int]:
        stmt = select(Lesson).where(
            Lesson.language_code == lang,
            Lesson.status != "archived",
            or_(
                Lesson.owner_user_id == user_id,
                Lesson.visibility == "shared",
            ),
        )
        if q: stmt = stmt.where(Lesson.title.ilike(f"%{q}%"))
        if visibility == "mine": stmt = stmt.where(Lesson.owner_user_id == user_id)
        if visibility == "shared": stmt = stmt.where(Lesson.visibility == "shared")
        total = (await self.session.execute(
            select(func.count()).select_from(stmt.subquery()))).scalar_one()
        stmt = stmt.order_by(Lesson.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
        items = (await self.session.execute(stmt)).scalars().all()
        return items, total
```

- [ ] **Router:**

```python
@router.get("/lessons", response_model=LessonListResponse)
async def list_lessons(
    request: Request, lang: str, tab: str = "lessons",
    q: str | None = None, visibility: str = "all",
    page: int = 1, page_size: int = 25, session=Depends(get_session),
) -> LessonListResponse:
    if request.state.user_id is None: raise HTTPException(401)
    items, total = await LessonRepo(session).list_for_user(
        user_id=request.state.user_id, lang=lang, q=q, visibility=visibility,
        page=page, page_size=page_size,
    )
    return LessonListResponse(
        items=[LessonSummary.model_validate(l, from_attributes=True) for l in items],
        total=total, page=page, page_size=page_size,
    )
```

- [ ] **Test, commit:** `feat(lessons): GET /api/lessons with filters and pagination`

---

### Task 25: `POST /api/lessons` (create from text)

- [ ] **Schema:**

```python
class CreateLessonRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    language_code: str = Field(pattern="^(en|ru|pt)$")
    raw_text: str = Field(min_length=1)
    visibility: Literal["private", "shared"] = "private"
```

- [ ] **Service:**

```python
async def create_lesson_from_text(
    *, user_id, title, language_code, raw_text, visibility, session,
) -> Lesson:
    lesson = Lesson(
        owner_user_id=user_id, title=title, language_code=language_code,
        raw_text=raw_text, visibility=visibility,
        word_count=len(raw_text.split()),
        status="ready",  # MVP: skip async processing
    )
    session.add(lesson); await session.flush()
    return lesson
```

- [ ] **Router:**

```python
@router.post("/lessons", status_code=201, response_model=LessonSummary)
async def create_lesson(body: CreateLessonRequest, request: Request, session=Depends(get_session)):
    if request.state.user_id is None: raise HTTPException(401)
    lesson = await create_lesson_from_text(
        user_id=request.state.user_id,
        title=body.title, language_code=body.language_code,
        raw_text=body.raw_text, visibility=body.visibility, session=session,
    )
    return LessonSummary.model_validate(lesson, from_attributes=True)
```

- [ ] **Test, commit:** `feat(lessons): POST /api/lessons creates ready lesson from text`

---

### Task 26: Frontend — language layout + library route shell

**Files:**
- Create: `frontend/src/routes/learn.$lang.tsx`
- Create: `frontend/src/routes/learn.$lang.library.tsx`
- Create: `frontend/src/components/AppTopBar.tsx`
- Create: `frontend/src/components/LanguagePicker.tsx`
- Create: `frontend/src/components/AvatarMenu.tsx`

- [ ] **`learn.$lang.tsx`** (layout с TopBar и language guard):

```tsx
import { Outlet, createRoute, redirect } from '@tanstack/react-router'
import { AppTopBar } from '@/components/AppTopBar'
import { rootRoute } from './__root'

export const learnLangRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/learn/$lang',
  beforeLoad: ({ params }) => {
    if (!['en', 'ru', 'pt'].includes(params.lang)) throw redirect({ to: '/' })
  },
  component: () => (
    <div className="min-h-screen">
      <AppTopBar />
      <main><Outlet /></main>
    </div>
  ),
})
```

- [ ] **`AppTopBar.tsx`** — logo + LanguagePicker + tabs (Library/Vocabulary) + AvatarMenu, по `docs/ui/library.md` §4.
- [ ] **`LanguagePicker.tsx`** — Dropdown из shadcn, items = `user.learning_languages`. Click → navigate `/learn/{newLang}/{currentSection}` + `meApi.update_language(...)` (на backend нужно добавить эндпоинт; либо сразу в onboarding endpoint расширить — ленивая опция: PATCH `/me/last-language`).

> Note: добавить минимальный `PATCH /me/last-language` endpoint (не выделяется в отдельную task — добавить в Task 13 service'е).

- [ ] **Commit:** `feat(frontend): add /learn/:lang layout with TopBar`

---

### Task 27: Library page — FilterRow + Import dialog

**Files:**
- Create: `frontend/src/features/library/{LibraryPage,FilterRow,ImportLessonDialog}.tsx`
- Create: `frontend/src/api/lessons.ts`

- [ ] **`api/lessons.ts`:**

```typescript
import { api } from './client'

export type LessonSummary = {
  id: string; title: string; language_code: string; word_count: number
  visibility: string; status: string; created_at: string
}

export const lessonsApi = {
  list: (lang: string, params: { tab?: string; q?: string; page?: number }) =>
    api<{ items: LessonSummary[]; total: number; page: number; page_size: number }>(
      `/api/lessons?lang=${lang}&` + new URLSearchParams(params as any).toString()
    ),
  create: (data: { title: string; language_code: string; raw_text: string; visibility?: string }) =>
    api<LessonSummary>('/api/lessons', { method: 'POST', body: JSON.stringify(data) }),
}
```

- [ ] **`FilterRow.tsx`** — search input (Zustand или local state) + Import button открывает dialog.
- [ ] **`ImportLessonDialog.tsx`** — shadcn Dialog с двумя tabs (Текст / Файл, файл скрыт в MVP); поля `title` и `raw_text`. На submit — `lessonsApi.create({ language_code: currentLang, ... })` → invalidate `['lessons', lang]` query → закрыть.
- [ ] **Commit:** `feat(library): add FilterRow with search and ImportLessonDialog`

---

### Task 28: SubTabs + LessonCarousel + LessonCard

**Files:**
- Create: `frontend/src/features/library/{LibraryPage,SubTabs,LessonCarousel,LessonCard,LessonCover}.tsx`

- [ ] **`LibraryPage.tsx`:**

```tsx
import { useSearch } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { lessonsApi } from '@/api/lessons'
import { useUserStore } from '@/stores/userStore'
import { FilterRow } from './FilterRow'
import { SubTabs } from './SubTabs'
import { LessonCarousel } from './LessonCarousel'

export function LibraryPage() {
  const { tab = 'continue' } = useSearch({ strict: false }) as { tab?: string }
  const lang = useUserStore((s) => s.currentLang)!
  const { data } = useQuery({
    queryKey: ['lessons', lang, tab],
    queryFn: () => lessonsApi.list(lang, { tab }),
  })

  return (
    <div className="container mx-auto py-6 space-y-6">
      <FilterRow />
      <SubTabs activeTab={tab} />
      <LessonCarousel items={data?.items ?? []} />
    </div>
  )
}
```

- [ ] **`SubTabs.tsx`** — кнопки `Продолжить изучение` / `Уроки`, меняют `?tab=`.
- [ ] **`LessonCarousel.tsx`** — горизонтальный list карточек с overflow-x-auto и стрелками ‹/›.
- [ ] **`LessonCard.tsx`** — 220×250, по `docs/ui/library.md` §8.1.
- [ ] **`LessonCover.tsx`** — авто-плейсхолдер: цвет = HSL от hash(title), показывает `language_code.toUpperCase()` крупно.
- [ ] **Commit:** `feat(library): add SubTabs, carousel and LessonCard`

---

### Task 29: Empty state + DoD smoke test

- [ ] **Empty state в `LibraryPage`:**

```tsx
{data?.items.length === 0 && (
  <div className="text-center py-20">
    <h2 className="text-xl font-semibold">У вас пока нет уроков</h2>
    <p className="text-muted-foreground">Импортируйте свой первый текст</p>
    <ImportLessonDialog trigger={<Button className="mt-4">+ Импортировать урок</Button>} />
  </div>
)}
```

- [ ] **Manual DoD smoke test** (zero-context engineer выполняет):

```bash
# Backend
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
cd backend && uv sync && uv run alembic upgrade head
FLINQ_INITIAL_ADMIN_EMAIL=admin@flinq.local uv run flinq serve

# Frontend (новый терминал)
cd frontend && corepack pnpm install && corepack pnpm dev

# Browser
# 1. Open http://localhost:5173 → redirected to /login
# 2. Click «Зарегистрироваться» → fill name, email=test@test.com, password=abcdefghij
# 3. Auto-redirected to /onboarding
# 4. Select UI=Русский, Learning=☑Português, Translation=Русский → Submit
# 5. Redirected to /learn/pt/library (empty state)
# 6. Click «+ Импортировать урок» → Текст tab → title=«Тест», text=«Olá mundo» → Save
# 7. Card appears with title, "1 word", PT placeholder cover
# 8. Click TopBar avatar → Logout → redirected to /login
```

Все 8 шагов должны пройти без ошибок в консоли.

- [ ] **Commit:** `feat(library): add empty state and complete DoD smoke test`
- [ ] **Final commit:** `chore: update README quickstart for auth + library MVP`

> ✅ Epic complete. DoD met.

---

## Self-Review

**Spec coverage:**
- ✅ ADR-0007 URL scheme `/learn/:lang/...` — Tasks 22, 26.
- ✅ ADR-0008 auth — Tasks 2 (password), 5 (sessions+CSRF), 9–14 (endpoints), 15 (CLI).
- ✅ ADR-0009 UI kit — Task 17.
- ✅ Domain model patch — Task 1 (onboarded_at, last_learning_language_code, user_learning_languages).
- ✅ login.md — Task 19.
- ✅ register.md — Task 20.
- ✅ onboarding.md — Tasks 13, 21.
- ✅ library.md (subset, без YouTube card / level slider / interactive tab) — Tasks 26–29.
- ✅ word_card.md — **не входит в этот эпик** (отдельный эпик).
- ✅ reader.md, vocabulary.md — **не входят в этот эпик**.

**Placeholder scan:**
- ⚠️ Task 21 (Onboarding form): полный код пишется по аналогии с LoginForm — указан паттерн, но не каждая строка. Inline TODO ноуинг — структура и API клиент описаны, реализация прямолинейна. Считаем приемлемым: zero-context engineer имеет шаблон LoginForm и docs/ui/onboarding.md §3.
- ⚠️ Task 26 (LanguagePicker): упомянута необходимость `PATCH /me/last-language` endpoint — указано в той же task'е, но не выделено отдельной task'ой. Это small endpoint (3 строки в service), не блокирующий. Если хочешь — выделю в Task 26.5.
- ⚠️ Task 28 (LessonCard, LessonCover): код не показан полностью — только описание. В реальном выполнении агент опирается на `docs/ui/library.md` §8.1 + tokens.

**Type consistency:**
- `MeResponse` (backend) ↔ `MeResponse` (frontend types) — поля совпадают.
- `RegisterRequest` ↔ `RegisterPayload` — совпадают (`display_name`, `email`, `password`).
- `LessonSummary` (backend) ↔ `LessonSummary` (frontend) — совпадают.
- `OnboardingRequest` ↔ `OnboardingPayload` — совпадают.

## Risks

| Риск | Митигация |
|---|---|
| testcontainers требует Docker daemon в CI | Уже зафиксировано в ADR-0006 — CI поднимает Docker |
| `PATCH /me/last-language` забыт в endpoint plan | Добавить как mini-task в Phase 2 (после Task 13) |
| Vite proxy конфигурация для API в dev | Проверить `vite.config.ts` — `proxy: { '/auth': 'http://localhost:8000', '/me': ..., '/api': ... }`; зафиксировать в Task 17 |
| Browser Secure-cookie на http://localhost | В dev отключить `secure=True` через `settings.is_dev` ветвление |
| FastAPI session middleware порядок — CSRF должен идти ПОСЛЕ session | Проверено в Task 5 |

---

## Execution Handoff

**Plan complete and saved to `docs/specs/2026-05-01-mvp-auth-and-library-plan.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — диспатчу свежий subagent на каждую task, ревью между ними, быстрая итерация. Хорошо для строгой TDD-дисциплины.
2. **Inline Execution** — выполняем в этой сессии через executing-plans skill, batch с checkpoint-ами.

**Какой подход?**
