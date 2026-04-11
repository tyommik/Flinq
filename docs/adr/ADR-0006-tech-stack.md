# ADR-0006 — Tech stack: Python 3.13 backend, React frontend, monorepo

- Статус: Accepted
- Дата: 2026-04-11
- Связан со: `docs/specs/2026-04-11-mvp-product-alignment-design.md`, `docs/architecture/2026-04-11-mvp-architecture-overview.md` §4, §5, ADR-0003

## Контекст

Архитектурный overview (§4) зафиксировал Python 3.13+ как baseline для backend'а, но оставил открытыми конкретные выборы: web framework, ORM, job queue, frontend stack, инструменты разработки и структуру репозитория. До первой строчки кода эти решения надо зафиксировать, иначе каждый модуль будет перепридумывать их заново.

Целевая аудитория — personal homelab + small team (см. decision log). Это означает:

- Минимум операционной сложности: поставка одним `docker compose up`, без оркестраторов и дополнительных сервисов.
- Один разработчик или небольшая команда — все решения должны быть читаемы и поддерживаемы без эксклюзивной экспертизы.
- Приемлемая производительность, но не пиковая: трафик personal инсталляции минимален, экзотические оптимизации не нужны.
- Self-hosted first: все зависимости должны работать без облачных сервисов (кроме опционального LLM endpoint'а, см. ADR-0003).

## Решение

### Python runtime и dependency management

- **Python**: минимум `3.13`, pin в `pyproject.toml` как `requires-python = ">=3.13"`. CI и production-образы привязаны к конкретной версии (`3.13.x`), обновление до новых minor'ов — отдельным PR после их stable-релиза.
- **Dependency / project manager**: **uv**. Использовать `uv.lock` как lockfile, `uv sync` для установки, `uv run` для запуска команд в проектном окружении. Это быстрее poetry на порядок и покрывает всё то же самое.
- **Docker base image**: `python:3.13-slim-bookworm`. Multi-stage build с отдельным `builder` этапом для компиляции зависимостей.

### Backend core

- **Web framework**: **FastAPI**. Async native, автоматическая генерация OpenAPI schema, богатая экосистема middleware, отличная интеграция с Pydantic. Альтернативы (Litestar, Starlette, Django) рассмотрены и отвергнуты — см. раздел «Альтернативы».
- **Validation / DTO**: **Pydantic v2**. Используется FastAPI по умолчанию. Rust-core делает валидацию дешёвой. Тот же Pydantic — для настроек через `pydantic-settings`.
- **ORM**: **SQLAlchemy 2.x** в async-режиме (`AsyncSession`). Type annotations в 2.x достаточно зрелые, `Mapped[...]` синтаксис читается и проверяется pyright/mypy.
- **Миграции**: **Alembic** с autogenerate. Стандартная связка с SQLAlchemy.
- **Database driver**: **asyncpg** для всего async-пути (API, большинство worker-задач). При необходимости sync-операций (например, management-команды) — **psycopg3** в sync-режиме.
- **HTTP client**: **httpx**. Async/sync в одном API, нативно используется и в application code, и в тестах через `httpx.AsyncClient` с `ASGITransport`.

### Queue и фоновые задачи

- **Job queue**: **Taskiq** с Redis broker и Redis result backend. Async native, активно развивается, поддерживает несколько брокеров (Redis для прода, in-memory для unit-тестов). ARQ рассмотрен и отвергнут: упражнение в анализе — у команды ARQ объявлен недостаток времени на поддержку, новых релизов не выходит, что создаёт технический долг на старте.
- **Scheduler**: встроенный Taskiq scheduler (`TaskiqScheduler`). Отдельный APScheduler не нужен.
- **Broker в тестах**: `InMemoryBroker` от Taskiq — быстрые тесты без внешнего Redis.

### Инструменты качества кода

- **Test runner**: **pytest** + **pytest-asyncio** (режим `asyncio_mode = "auto"`).
- **Integration tests**: **testcontainers-python** для поднятия настоящего Postgres и Redis в Docker при CI. Миграции и SQL должны проверяться на реальном Postgres, а не на SQLite.
- **HTTP API tests**: `httpx.AsyncClient` с `ASGITransport(app=app)` — без fakeserver'ов.
- **Linter / formatter**: **ruff** в двух ролях (`ruff check` и `ruff format`). Заменяет black, isort, flake8, pylint, pyupgrade. Один конфиг в `pyproject.toml`.
- **Type checker**: **pyright** в strict mode (с селективными escape hatches для мест, где SQLAlchemy ещё не идеально типизирован). Быстрее mypy, лучше inference для Python 3.13 features.
- **Pre-commit**: **pre-commit** с хуками на ruff и pyright. Запускается локально и в CI.
- **Coverage**: **coverage.py** + `pytest-cov`. Целевой минимум на первый год — не формализован (см. open questions).

### Сопутствующие backend-библиотеки

- **Logging**: **loguru**. Один импорт, без boilerplate, JSON-форматтер доступен из коробки, ротация и уровни конфигурируются в `settings`. Structured logs — требование `architecture overview §13` — обеспечиваются через JSON-sink loguru.
- **CLI (admin-команды)**: **typer**. От автора FastAPI, тот же UX с type hints. Команды вида `flinq dictionary refresh`, `flinq export-user`, `flinq run-migrations`.
- **Settings**: **pydantic-settings**. Env-переменные, `.env` файлы, валидация, типизация.
- **Auth / password hashing**: **argon2-cffi** для хеширования паролей. Без отдельного authentication framework — session-based cookies, руками через FastAPI dependency.
- **Pagination / filters**: без отдельной библиотеки. Простые query-параметры и SQL-queries в каждом endpoint'е, шаблонизировать при необходимости.
- **Object storage adapter**: собственный интерфейс поверх локальной файловой системы (см. `architecture overview §8.3`). Без `boto3` / `minio` в MVP.

### Frontend

- **UI framework**: **React 19+** (или актуальный major на момент старта).
- **Language**: **TypeScript** в strict mode.
- **Build tool**: **Vite**.
- **Package manager**: **pnpm**. Быстрее npm и yarn, лучше работает с monorepo-style зависимостями, меньший `node_modules`.
- **State management**: **Zustand** для клиентского UI-state (reader position, UI toggles), **TanStack Query** для server-state (lesson data, vocabulary, stats). Разделение эти два слоя — сознательное: client state и server state имеют разные жизненные циклы и кэширующие стратегии.
- **Router**: **TanStack Router**. Полная типизация URL-параметров критична для reader/lesson/review маршрутов, где опечатка в query-param будет ловиться компилятором.
- **Forms**: **TanStack Form** (или `react-hook-form` как fallback). В MVP форм мало — выбор финализируется при первой реальной форме.
- **Styling**: **Tailwind CSS v4**. Быстрый dev-loop, удобен для reader'а с массой подсвеченных токенов и динамических состояний.
- **Icons**: **lucide-react**. Tree-shakeable, широкое покрытие.
- **HTTP client**: `fetch` через `TanStack Query`. Без отдельной `axios`-абстракции.
- **Testing**: **Vitest** + **@testing-library/react** + **jsdom**.
- **Linter / formatter**: **ESLint** (flat config) + **Prettier** (или **Biome**, решить отдельно на этапе setup'а).
- **OpenAPI → TS types**: **openapi-typescript** или **orval**, запускается скриптом `scripts/generate-api-types.sh`, коммитит сгенерированные типы в `frontend/src/api/types.ts`.

### Repository layout

**Monorepo**. Один git-репозиторий, две независимые подпапки — `backend/` и `frontend/` — со своими pyproject.toml / package.json, своими lockfile'ами, своими Dockerfile'ами. Общий root для документации, docker-compose, CI, scripts.

```
Flinq/
├── AGENTS.md
├── AGENTS_RU.md
├── README.md
├── docker-compose.yml
├── docker-compose.dev.yml
├── .github/
│   └── workflows/
│       ├── backend.yml      # paths: backend/**
│       ├── frontend.yml     # paths: frontend/**
│       └── docker.yml       # сборка образов при тегах release
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── Dockerfile
│   ├── src/flinq/
│   │   ├── api/             # FastAPI routes
│   │   ├── core/            # cross-cutting: config, logging, db, security
│   │   ├── modules/         # доменные модули из architecture overview §7
│   │   │   ├── identity/
│   │   │   ├── lesson_library/
│   │   │   ├── reader_state/
│   │   │   ├── vocabulary/
│   │   │   ├── dictionary/
│   │   │   ├── review_engine/
│   │   │   ├── ai_translation/
│   │   │   ├── statistics/
│   │   │   └── admin/
│   │   ├── worker/          # Taskiq entrypoint и task registrations
│   │   └── cli/             # typer admin-команды
│   ├── migrations/          # Alembic
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── Dockerfile
│   ├── src/
│   │   ├── api/             # generated types + query hooks
│   │   ├── routes/          # TanStack Router
│   │   ├── features/        # feature-based UI modules
│   │   ├── components/      # shared UI
│   │   ├── stores/          # Zustand stores
│   │   └── lib/             # utilities
│   └── tests/
├── docs/
│   ├── lingq-like-self-hosted-spec-2026.md
│   ├── specs/
│   ├── adr/
│   └── architecture/
└── scripts/
    ├── generate-api-types.sh
    ├── setup-dev.sh
    └── migrate.sh
```

**Принципы:**

- Backend и frontend независимы с точки зрения сборки: можно собрать только backend или только frontend.
- В production (`docker-compose.yml`) Flinq поставляется как **два контейнера**: `app-api` и `app-worker`, оба из одного `backend/` кода. Frontend собирается в статические assets отдельным stage `backend/Dockerfile` и раздаётся FastAPI через `StaticFiles` — следует `architecture overview §5.3`.
- В dev (`docker-compose.dev.yml`) frontend запускается отдельно через Vite dev server с proxy на backend — hot reload для обоих.
- CI-джобы запускаются селективно по путям (`paths: backend/**` и `paths: frontend/**`), чтобы не тратить время на то, что не менялось.

### Не выбираем сейчас (пока не появится реальный код)

Эти решения **можно** отложить, потому что они локальны, обратимы, и выбор не меняет архитектуры:

- Прекоммит tools конкретного фронтенда (Biome vs ESLint+Prettier) — уточним при setup.
- Формы: TanStack Form vs react-hook-form — при первой реальной форме.
- Specific UI компонент-библиотека (shadcn/ui, Park UI, RadixUI напрямую) — при первой серьёзной композиции.
- Specific cookie/session библиотека — при реализации auth-модуля.

## Последствия

**Положительные:**

- **Consistent toolchain**: uv, ruff, pyright — все три от Astral, одна философия, быстрые, современные. Это сильно сокращает время на «настройку настройки».
- **Async end-to-end**: FastAPI + Taskiq + SQLAlchemy async + httpx async — один асинхронный стиль по всему backend'у, без sync/async боли.
- **Type safety end-to-end**: pyright strict на backend'е, TypeScript strict на frontend'е, OpenAPI-generated типы между ними — ошибка в shape API ловится на компиляции, а не в runtime.
- **Lockfile-driven reproducibility**: `uv.lock` и `pnpm-lock.yaml` гарантируют воспроизводимую сборку.
- **Monorepo atomicity**: API и UI изменяются в одном PR. Нет рассинхронизации релизов.
- **Одна поставка**: `docker compose up` — и весь стек работает. Это главный критерий личного self-hosted продукта.
- **Прозрачный upgrade path**: все выборы — industry-standard на апрель 2026, обновления будут регулярные, заброшенных зависимостей нет (см. ARQ в альтернативах — как раз тот случай, которого мы избегаем).

**Отрицательные (принятые):**

- **Async требует дисциплины**: случайная синхронная операция в async-контексте блокирует event loop. Это известный класс ошибок, ловится code review и pyright, но существует.
- **uv и Taskiq моложе альтернатив**: poetry и Celery зрелее, у них больше Stack Overflow ответов. Принимаем на себя небольшой риск «незнакомого окружения» ради скорости и современности.
- **pyright vs mypy**: часть экосистемы Python всё ещё ориентируется на mypy. Некоторые `# type: ignore` комментарии от сторонних библиотек нацелены на mypy, pyright на них ругается иначе. Решаем локально в `pyrightconfig.json`.
- **React vs более модные альтернативы**: Svelte/Solid теоретически легче и быстрее. React выбран ради экосистемы, а не ради изящества.
- **SQLAlchemy 2.x async**: async-паттерн в ORM сложнее, чем sync. Для большинства запросов это ок, но lazy loading в async-контексте — источник ошибок. Решение: использовать `selectinload` / `joinedload` явно, не полагаться на lazy.
- **Monorepo growth**: при сильном росте кода CI-джобы могут удлиниться, даже с path filters. Мы не ожидаем такой рост в обозримом будущем, но если он случится — переедем на Turborepo/Nx или выделим frontend в отдельный repo. Обратимо.

## Альтернативы (отвергнуты)

### Web framework

- **Litestar**: младше FastAPI, быстрее в бенчмарках, но экосистема, документация, middleware, community — всё ещё слабее. Принимаем FastAPI как «boring choice».
- **Starlette напрямую**: на одну прослойку ниже FastAPI. Выигрыш — минус одна зависимость. Проигрыш — ручная работа над тем, что FastAPI делает бесплатно (dependency injection, request parsing, OpenAPI). Не оправдано.
- **Django + DRF**: batteries included, но все batteries не-async, админка для нас избыточна, ORM хороша, но связана с остальным Django. Слишком тяжело для scope'а.

### Job queue

- **ARQ**: исходно был нашим первым выбором. Отвергнут: текущий статус поддержки не соответствует production-гарантиям. Taskiq — прямая замена с лучшей поддержкой.
- **Celery**: зрелая классика, но не async, тяжёлая конфигурация, серьёзный ops overhead, не вписывается в целевую self-hosted аудиторию.
- **Dramatiq**: async-light, неплохая альтернатива, но Taskiq развивается активнее и имеет встроенный scheduler.
- **Procrastinate** (Postgres-based queue): соблазнительно убрать Redis из стека. Но требует Postgres-specific настроек, менее зрела, fewer adapters. Redis остаётся в стеке для cache/ephemeral state независимо — убрать его как queue backend не даёт большой экономии.
- **RQ**: sync-only, простой, но не подходит async-first стеку.

### ORM

- **SQLModel**: удобнее SQLAlchemy за счёт объединения Pydantic и ORM модели. Отвергнут: такое объединение мешает разнести API-layer (Pydantic schemas) и persistence-layer (ORM models). Явное разделение на старте дороже, но платится на протяжении всего жизненного цикла кода.
- **Piccolo**: async native, хорошая работа с миграциями, но community заметно меньше, меньше гарантии долгосрочной поддержки.
- **Tortoise ORM**: ORM в стиле Django, async. Community меньше, чем у SQLAlchemy, меньше инструментов.

### Dependency management

- **poetry**: зрелый, стабильный, хорошо документирован. Отвергнут: медленный (особенно resolve), uv даёт тот же UX в разы быстрее. Переезжать позже с poetry на uv — несложно, но нулевой смысл начинать с медленного инструмента.
- **pdm**: работает, PEP 582 поддержка, но меньше momentum чем uv.
- **pip-tools + venv**: слишком ручное, неудобно для многих команд.

### Logging

- **structlog**: хорошая библиотека для «индустриальных» сценариев с structured logging и кастомными пайплайнами. Отвергнут: требует больше церемоний (processor chains, binders), что избыточно для personal/small-team scope. Loguru даёт JSON output с минимумом boilerplate.
- **stdlib logging**: работает, но неудобно конфигурировать, многословно. Не добавляет value.

### Frontend framework

- **Svelte / SvelteKit**: современный, компактный, элегантный. Экосистема всё ещё меньше чем React, меньше готовых компонентов для сложного reader UX (DnD, context menus, virtual scrolling).
- **Vue 3**: зрелая альтернатива, большая экосистема. Выбор между Vue и React — вопрос привычки; React выигрывает за счёт большего количества компонентов и библиотек конкретно для reader/editor сценариев.
- **Solid**: быстрый, reactive, но экосистема ещё уже, чем у Svelte.
- **HTMX + server-rendered templates**: привлекательно минимализмом, но reader с интерактивными кликами на каждое слово, подсветкой по статусу, bulk-known операциями и картами перевода потребует много JS в любом случае. Full SPA проще поддерживать.

### Repository layout

- **Separate repos (backend и frontend)**: стандартный паттерн для SaaS с несколькими клиентами или разными командами. Для self-hosted продукта, поставляемого как единое целое, создаёт искусственный рассинхрон между API и UI, требует дополнительной оркестрации версий и shared types. Отвергнут — см. также §«Monorepo growth» в последствиях.

### Pyright vs mypy

- **mypy**: исторический стандарт, лучше интеграция с некоторыми библиотеками, особенно с teaching-oriented настройками. Отвергнут ради скорости и качества inference pyright'а для Python 3.13+. Мы можем поменять решение локально, если на практике pyright создаст проблемы.

## Открытые вопросы

- **Точный cookie/session-library**: `starlette.middleware.sessions` достаточен или нужен специализированный (`fastapi-users`, `authx`). Решить при реализации identity-модуля.
- **Object storage abstraction interface** — контракт (sync или async, какие операции): финализировать при реализации lesson import'а.
- **Coverage threshold** для `pytest --cov`: определить после первого сквозного набора тестов.
- **Dev watchdog**: `uvicorn --reload` на backend, Vite HMR на frontend — ок, но нужна единая команда `make dev` или `docker compose -f docker-compose.dev.yml up`, чтобы не жонглировать терминалами.
- **Frontend UI component library (shadcn/ui vs что-то другое)**: решать при первом реальном UI-дизайне reader'а.
- **Upgrade path до Python 3.14**: после stable-релиза — отдельный PR с проверкой всех зависимостей.