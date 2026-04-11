# AGENTS_RU.md

Инструкции для AI-агентов (Claude Code, Cursor, Copilot и аналогичных), работающих в репозитории Flinq.

## Состояние проекта

Flinq — self-hosted платформа для изучения языков по модели content-driven learning, аналог LingQ. Текущая фаза — **pre-implementation**. В репозитории лежат только спецификации и записи архитектурных решений; прикладного кода пока нет.

Прежде чем предлагать или писать какой-либо код, прочитай:

1. `docs/lingq-like-self-hosted-spec-2026.md` — исходная продуктовая спецификация (Draft v1, 2026-04-11).
2. `docs/specs/2026-04-11-mvp-product-alignment-design.md` — decision log по MVP. Закрывает открытые вопросы из §16–17 спеки.
3. `docs/architecture/2026-04-11-mvp-architecture-overview.md` — высокоуровневая архитектура (модульный монолит + worker, Python 3.13+).
4. `docs/adr/ADR-0001-unit-of-learning-token-level.md`
5. `docs/adr/ADR-0002-word-status-model-and-reader-ui.md` — **superseded by ADR-0005**, сохраняется как исторический артефакт.
6. `docs/adr/ADR-0003-llm-provider-openai-compatible.md`
7. `docs/adr/ADR-0004-dictionary-wiktionary-provider.md`
8. `docs/adr/ADR-0005-word-status-model-lingq-levels.md` — текущая статусная модель слов: `new / tracked / known / ignored` с confidence `0..5`.
9. `docs/adr/ADR-0006-tech-stack.md` — Python + React tech stack, repository layout, инструменты разработки.

Продуктовое направление зафиксировано этими документами. Не возвращайся к вариантам, которые явно отвергнуты. Если принятое решение нужно изменить — напиши новый ADR или переведи существующий в статус `Superseded`. Молча переопределять решения нельзя.

## Обзор продукта

Content-driven изучение языков: пользователь импортирует реальные тексты, читает их в интерактивном reader'е, сохраняет незнакомые слова и фразы в личный словарь, повторяет их через SRS, получает контекстные AI-переводы. Всё работает на сервере, принадлежащем пользователю.

Пять продуктовых слоёв (из §15 спеки):

1. Content ingestion — импорт и подготовка контента
2. Interactive reader/player — интерактивное чтение
3. Personal vocabulary и phrase memory — личный словарь слов и фраз
4. AI assistance — AI-слой помощи
5. Analytics и self-hosted administration — статистика и администрирование инсталляции

## Ключевые продуктовые решения (краткая сводка)

Полное обоснование — в decision log и ADR. Этот раздел — справочник, а не источник истины.

### Границы MVP

- **Tenancy:** single-tenant self-hosted.
- **Клиент:** web-first responsive. Без нативного мобильного, без PWA, без offline.
- **Аудитория:** только learner. Никаких teacher/LMS-фич.
- **Библиотека:** приватный импорт + shared library внутри инстанса. Поля source/license/author обязательны для shared-контента.
- **Форматы импорта:** только `.txt` и `.md`. PDF/EPUB/сканы обрабатываются **внешним OCR-сервисом** со своим API, который возвращает `.md`.
- **Языки изучения:** EN, RU, PT.
- **Языки UI:** EN, RU.
- **Аутентификация:** email + password. Без SSO.
- **Доставка:** Docker Compose. Целевой класс — personal homelab + small team.

### Единица обучения — ADR-0001

- Единица обучения = **Token** (поверхностная словоформа), а не лемма.
- Каждая словоформа учится отдельно, как в LingQ: `poder`, `pode`, `pudesse`, `pudessem` — четыре разные карточки.
- **Сущности `Lemma` нет** в модели данных.
- Нормализация при сохранении: Unicode NFC → lowercase → обрезание ведущей и замыкающей пунктуации. Диакритика сохраняется. Внутренние дефисы и апострофы сохраняются.
- `Phrase` — отдельная first-class сущность со своим статусом и своим SRS-item.
- **Единая SRS-очередь** для Token и Phrase (одна review-сессия, допустимы разные форматы карточек).
- Пользователь может вручную редактировать и текст записи, и перевод.

### Статусная модель слов — ADR-0005

Четыре статуса: `new`, `tracked`, `known`, `ignored`. У `tracked` есть поле `confidence` в диапазоне `0..5`.

| Статус | Визуал в reader | Содержимое карточки при клике |
|---|---|---|
| `new` | бледно-голубой фон | AI-перевод первым (с меткой AI-generated), словарный ниже. Кнопки: **Add to study** (→ `tracked`, confidence 1), **Ignore** (→ `ignored`), **I know this** (→ `known`) |
| `tracked` | жёлтый фон (опциональный confidence-gradient) | Сохранённый пользовательский перевод, индикатор confidence `0..5`. Кнопки: Edit translation, Adjust confidence, Move to known, Move to ignored |
| `known` | без выделения | Комбинированный AI + словарь, опциональная подсказка. Кнопка: Move back to tracked (edge case) |
| `ignored` | без выделения (в MVP визуально неотличим от `known`) | Короткая заметка «Ignored». Кнопка: Reactivate (→ `tracked`) |

Переходы:
- `new → tracked`: пользователь кликнул и нажал «Add to study». Confidence стартует с `1` (или с выбранного пользователем значения).
- `new → known`: **per-page bulk** — при нажатии «next page» все `new` occurrences на текущей странице становятся `known`. Не затрагивает `tracked`/`ignored`.
- `new → ignored`: явное действие «Ignore» в карточке. Типично для имён собственных, чисел, мусорных (неправильно сегментированных) токенов, редких технических терминов.
- `tracked → tracked` (`confidence ±1`): ответ в review session (правильно → `+1`, ошибка → `-1`, clamp в `[0, 5]`).
- `tracked → known`: SRS-graduation (успешное повторение при `confidence = 5`) или ручная пометка.
- `tracked → ignored`: ручная пометка.
- `known → tracked`, `ignored → tracked`: ручной revert (edge case).
- Прямых переходов между `known` и `ignored` нет — только через `tracked`.

`ignored` **не** входит в счётчик `known`. Это главное продуктовое отличие: имена собственные и мусорные токены не загрязняют метрику «известных слов».

Reader обязан поддерживать undo последнего bulk-known действия.

### AI — ADR-0003

- **AI опционален.** Базовый продукт должен работать без AI-провайдера. Словарь, reader, личный словарь, SRS и статистика функционируют без AI.
- **Скоуп MVP:** только контекстный перевод выделения. Без объяснения грамматики, без chat'а, без генерации упражнений.
- **Провайдер:** один адаптер, совместимый с OpenAI Chat Completions API. Покрывает OpenAI, OpenRouter, vLLM, LM Studio, LocalAI и Ollama (у которой есть OpenAI-compat endpoint).
- **Конфигурация** — через переменные окружения Docker Compose-сервиса:
  ```
  FLINQ_LLM_BASE_URL=https://api.openai.com/v1
  FLINQ_LLM_API_KEY=sk-...
  FLINQ_LLM_MODEL=gpt-4o-mini
  FLINQ_LLM_ENABLED=true
  ```
- `FLINQ_LLM_ENABLED=false` — admin kill-switch. Reader и словарь продолжают работать, AI-секции исчезают из карточек.
- AI-ответы всегда помечаются как AI-generated. Канонический перевод карточки — это то, что пользователь написал сам; AI-ответ — черновик.
- Кэш AI-ответов **per-user**, ключ `(user_id, model, prompt_hash)`. Без шаринга между пользователями.
- Ретрай: простой экспоненциальный backoff, максимум 3 попытки, на сетевых ошибках и 5xx.

### Словарь — ADR-0004

- **Источник:** Wiktionary dump через [Kaikki.org](https://kaikki.org/), лицензия CC-BY-SA 4.0.
- Дамп загружается в локальные таблицы БД при setup'е. Обновление — ручное действие админа.
- **Атрибуция лицензии обязательна** в каждой карточке, где показаны словарные данные. Это не админ-настройка.
- Интерфейс `DictionaryProvider` существует с первого дня, чтобы в будущем добавлять дополнительные источники. В MVP одна реализация — `WiktionaryDictionaryProvider`.
- Персональные переводы пользователя никогда не сливаются обратно в словарную базу — они живут только в личном словаре.

### Метрики

Метрики в MVP:
- Количество прочитанных токенов.
- Количество записей в статусе `tracked` (слова + фразы).
- Количество записей в статусе `known` (слова + фразы). **Не включает `ignored`.**
- Количество записей в статусе `ignored` (слова + фразы) — хранится, но не показывается как hero metric.

Без streak. Без времени чтения. Без heatmap. Оставляем место для осмысленных метрик после реальных данных использования.

### Privacy

- Экспорт всех пользовательских данных в JSON (кнопка в профиле).
- Hard-delete профиля (общие словари и shared-контент не затрагиваются).
- Admin kill-switch для всех внешних AI-вызовов (см. `FLINQ_LLM_ENABLED`).
- Провайдерские секреты в MVP лежат в env-переменных контейнера — шифрования секретов на уровне БД в MVP нет.

## Non-goals (не предлагать для MVP)

Если пользователь просит что-то из этого списка, укажи ему на `docs/specs/2026-04-11-mvp-product-alignment-design.md` §13 и сначала запроси явное изменение скоупа.

- Нативные мобильные приложения (iOS, Android).
- PWA и полноценный offline.
- Импорт аудио/видео, TTS, STT, alignment, shadowing, speaking practice.
- Teacher/coach сценарии, LMS, cohort analytics.
- SSO, tenant isolation, UI управления квотами.
- Marketplace или федерация между инсталляциями.
- Social feed, комментарии к урокам.
- Встроенный каталог готовых уроков, поставляемый с продуктом.
- Автоматическая поддержка большого количества языков на старте.
- Shared AI-кэш между пользователями.
- FSRS или иной адаптивный SRS в первом релизе (простой SM-2-класса допустим).
- Dashboard метрик с heatmap, cohort analytics, retention-кривыми.
- Привязка phrase/word к лемме (явно отвергнуто в ADR-0001).
- Удаление per-page bulk-known перехода из reader'а (явно требуется ADR-0005).
- Учёт `ignored`-записей в метрике `known` (явно отвергнуто в ADR-0005 — это главное улучшение по сравнению с superseded ADR-0002).
- AI как первичный источник перевода для known слов (AI-first) или как замена словаря.
- Anthropic / Google / любые не OpenAI-совместимые LLM-бэкенды в MVP (при необходимости — через OpenRouter).

## Open questions (сознательно отложено)

Эти пункты перечислены в `docs/specs/2026-04-11-mvp-product-alignment-design.md` §11 и должны быть решены по мере блокировки:

- Конкретный алгоритм SRS (SM-2 vs FSRS vs собственный).
- Правила токенизации для edge-cases (апострофы, дефисы, числа внутри слов).
- Матчинг фраз между уроками (точное совпадение vs морфологические варианты).
- Размер «страницы» в reader'е (слова? абзацы? высота viewport'а?).
- Процедура backup/restore и её владелец.
- Rate limiting внешних AI-вызовов.
- Размещение атрибуции CC-BY-SA в UI.

Когда один из пунктов решается в ходе имплементации, зафиксируй его в новом ADR и удали из списка open questions.

## Архитектура

**TBD.** Проектирование архитектуры и модели данных — следующая запланированная фаза. Список высокоуровневых сервисов из §10 спеки — отправная точка, а не обязательство:

- `web-app` (UI для learner/admin)
- `api-gateway` / backend API
- `content-ingestion-service`
- `dictionary-service`
- `ai-orchestrator`
- `review-engine` (SRS)
- `stats-service`
- `worker` (фоновые задачи)
- `postgres` (транзакционные данные)
- `object storage` (медиа, импорты)
- `redis` (очереди, кэши, ephemeral state)

MVP скорее всего схлопнет несколько из этих сервисов в один backend-процесс. Финальная структура будет зафиксирована в архитектурной фазе и записана в новый ADR.

Этот раздел будет заполнен описанием директорий, data flow и ответственности компонентов, когда появится код.

## Tech stack (ADR-0006)

**Backend** — Python 3.13+, FastAPI, Pydantic v2, SQLAlchemy 2.x async, Alembic, asyncpg, httpx, Taskiq (Redis broker), loguru, typer, pydantic-settings, argon2-cffi. Package manager — **uv**. Linter/formatter — **ruff**. Type checker — **pyright**.

**Frontend** — React 19+, TypeScript strict, Vite, pnpm. State: **Zustand** (client) + **TanStack Query** (server). Routing: **TanStack Router**. Styling: **Tailwind CSS v4**. Icons: **lucide-react**. Tests: **Vitest** + **@testing-library/react**.

**Repository layout** — monorepo с подпапками `backend/` и `frontend/` в корне. Каждая — самодостаточный проект со своим lockfile и Dockerfile. CI-джобы отфильтрованы по путям: `backend/**` и `frontend/**` запускают независимые workflow.

**Доставка** — контейнеры `app-api` и `app-worker` из одного `backend/` кода. Frontend собирается как статические assets в multi-stage Docker-сборке и раздаётся FastAPI через `StaticFiles`. Поставка одной командой `docker compose up`.

## Команды

**TBD.** Команды будут заполнены после scaffolding'а проекта. Ожидаемый набор:

- `uv sync` — установить backend-зависимости
- `uv run flinq serve` — запустить app-api в dev-режиме
- `uv run flinq worker` — запустить Taskiq worker
- `uv run pytest` — backend-тесты
- `uv run ruff check . && uv run ruff format .` — линтер и форматтер
- `uv run pyright` — тайпчек
- `uv run alembic upgrade head` — применить миграции
- `pnpm install` (в `frontend/`) — установить frontend-зависимости
- `pnpm dev` — запустить Vite dev server
- `pnpm test` — frontend-тесты
- `docker compose -f docker-compose.dev.yml up` — полный dev-стек

## Тестирование

- **Backend**: pytest + pytest-asyncio, testcontainers-python для настоящих Postgres/Redis в интеграционных тестах, `httpx.AsyncClient` с `ASGITransport` для API-тестов. Каждый доменный модуль из §7 архитектурного overview должен иметь unit-тесты на публичное service API.
- **Frontend**: Vitest + @testing-library/react + jsdom. Компонентные тесты рядом с исходниками. Интеграционные тесты на flow reader'а, операции со словарём, review-сессию.
- **Никаких моков БД** в интеграционных тестах — только testcontainers, не SQLite.

## Схема БД

**TBD.** Основные планируемые сущности (из §9 спеки с поправками ADR-0001):

- `User`, `UserProfile`
- `Lesson`, `LessonSegment`, `LessonSource`
- `Token` (единица обучения, ADR-0001), `Phrase`
- `DictionaryEntry`, `DictionaryTranslation`, `DictionaryExample`
- `PersonalDictionaryEntry` (связка User ↔ Token/Phrase со статусом, переводом, заметками)
- `ReviewItem`, `ReviewEvent`
- `AIRequest`, `AIResponse`
- `StatsSnapshot`, `Goal`
- `Course`, `Collection`

Итоговая схема будет зафиксирована в ADR до написания миграций.

## Деплой

**TBD.** Docker Compose — подтверждённый формат доставки. Конвенции env-переменных для LLM — см. ADR-0003. Kubernetes / Helm — вне скоупа MVP.

## Правила для агентов, работающих в этом репозитории

1. **Сначала читай decision log и релевантные ADR.** Продуктовое направление зафиксировано; не поднимай закрытые решения в разговоре повторно.
2. **Соблюдай non-goals.** Если пользователь просит что-то из non-goals — укажи на документ и запроси явное изменение скоупа. Не имплементируй молча.
3. **Изменение решений требует ADR.** Не редактируй принятые ADR по месту. Напиши новый со ссылкой на старый и переведи старый в статус `Superseded`.
4. **Языковые конвенции:**
   - Основной язык общения с пользователем — русский.
   - Код, идентификаторы, API-схемы, сообщения коммитов, заголовки PR — английский.
   - Design docs, ADR, decision logs — в языке окружающего документа (текущие документы на русском).
5. **Семантика токенизации и статусов** тонкая — ADR-0001 и ADR-0005 обязательны к прочтению перед любыми изменениями, связанными с словарём. Не добавляй специальную морфологическую обработку для русского; LingQ-модель принята сознательно.
6. **Когда AI выключен** (`FLINQ_LLM_ENABLED=false`), продукт должен работать, и reader должен рендерить карточки — просто без AI-секций. У каждого AI-касательного code path должна быть такая graceful degradation.
7. **Никогда не коммить провайдерские секреты.** API-ключи живут только в переменных окружения или в локальном `.env` разработчика (в `.gitignore`).
8. **Не вводи зависимости на морфологические анализаторы** (`pymorphy3`, `spaCy`, `stanza`) в ядре без ADR. ADR-0001 явно отверг этот класс зависимостей для слоя обучения.
9. **Атрибуция CC-BY-SA для словарных данных обязательна.** Любой рендер карточки должен включать указание Wiktionary.
10. **Спрашивай перед деструктивными действиями.** Никаких force-push, переписывания смердженных коммитов, удаления веток или томов без явного разрешения пользователя.