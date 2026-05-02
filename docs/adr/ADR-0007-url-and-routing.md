# ADR-0007 — URL scheme and routing strategy

- Статус: Accepted
- Дата: 2026-05-01
- Связан со: `docs/specs/2026-04-11-mvp-product-alignment-design.md` §10.1 (поддерживаемые языки), ADR-0006 (frontend stack: TanStack Router), `docs/ui/library.md` §2, `docs/ui/vocabulary.md` §2, `docs/ui/reader.md` §2, `docs/ui/onboarding.md` §5

## Контекст

UI-спеки писались с разнобоем по URL-стратегии: где-то `lang` был фильтром, где-то path-сегментом, где-то `?seg=` использовался для deep-link, в других местах `?view=`. Перед стартом frontend-эпика нужно зафиксировать единое правило — иначе TanStack Router придётся переписывать после первой пары feature'ов.

Учебная единица в Flinq — пара `(user, learning_language)`. Большинство экранов (library, vocabulary, review, stats, reader) по природе scoped именно по этому языку. Multi-select `?lang=...` filter размывает естественную модальность «я сейчас учу португальский».

## Решение

### Path-схема

Все language-scoped экраны используют префикс `/learn/:lang/...`, где `:lang ∈ {en, ru, pt}`:

| Экран | URL |
|---|---|
| Библиотека | `/learn/:lang/library` |
| Урок (reader) | `/learn/:lang/lessons/:lessonId` |
| Словарь | `/learn/:lang/vocabulary` |
| Повторение | `/learn/:lang/review` |
| Статистика | `/learn/:lang/stats` |

Account-level и auth-экраны **без** `:lang`:

| Экран | URL |
|---|---|
| Логин | `/login` |
| Регистрация | `/register` |
| Onboarding | `/onboarding` |
| Настройки | `/settings/profile`, `/settings/preferences`, `/settings/data` |
| Admin | `/admin/*` |

### Корневой редирект

- `/` для авторизованного — редирект на `/learn/:lang/library`, где `:lang = user_settings.last_learning_language_code` (поле добавляется в domain model).
- `/` для гостя — редирект на `/login`.
- Старые URL вида `/library`, `/vocabulary`, `/lessons/:id` (без `:lang`) при появлении обрабатываются редиректом на `/learn/:lang/...` с подстановкой `last_learning_language_code`.

### Query-параметры

Только для **major navigation tabs**, у которых deep-link имеет смысл:

| Экран | Допустимые query | Default |
|---|---|---|
| `/learn/:lang/library` | `?tab=continue\|lessons` | `continue` |
| `/learn/:lang/vocabulary` | `?tab=all\|words\|phrases\|due` | `all` |

Auth-flow исключение: `?next=` на `/login` для post-login redirect — это одноразовый параметр auth-flow, не application state.

### Client-state, не URL

Всё остальное живёт в **client-state** (Zustand store страницы или local component state):

- search query;
- фильтры (visibility, status, confidence range, теги, дата);
- sort;
- page и pageSize;
- view mode (page vs sentence в reader);
- текущий segment (используется server-side `reader_positions`).

Refresh страницы ресетит client-state до default'ов — это сознательно: URL отражает **место**, не **состояние просмотра**.

### Language picker

В global TopBar добавляется чип `🇵🇹 Português ▾` рядом с логотипом. Список — только изучаемые языки пользователя из `user_learning_languages` (см. domain model patch). Переключение:

1. Меняет первый сегмент path (`/learn/pt/library` → `/learn/ru/library`).
2. Обновляет `user_settings.last_learning_language_code` (debounced PATCH).

### UI-язык

UI-язык (`user_profiles.ui_language_code`) **не отражается в URL**. Применяется через i18next, persist'ится через cookie/header. Это account preference, не контекст страницы. Меняется через `/settings/preferences`.

## Последствия

**Положительные:**

- Естественная модальность UX «я сейчас в португальском контексте» — однозначна.
- Vocabulary, Review, Stats не нуждаются в `?lang=` фильтре; backend упрощается до `WHERE language_code = :lang`.
- Deep-links стабильны и читаемы.
- Минимум query-параметров — TanStack Router конфигурируется проще, меньше сериализационных багов.
- Backend получает `lang` из path как часть route-params, не нужно парсить query.

**Отрицательные (принятые):**

- Refresh страницы ресетит фильтры/поиск — пользователь, который привык к URL-state, может удивиться. Принято: это редкий кейс, поведение можно изменить локально (один store с persist в localStorage), если появится реальный запрос.
- Multi-language users должны явно переключать язык через picker — нельзя одновременно показать «все мои tracked items по всем языкам». Принято: это редкий сценарий, для аналитических целей будет отдельный экран `/me/all-languages-overview` в Phase 2.
- Смена `last_learning_language_code` при каждом переключении создаёт write-traffic. Решается debounce'ом 1сек.

## Альтернативы (отвергнуты)

- **Query-based language (`/library?lang=pt`)** — изначальная схема в первых UI-spec'ах. Отвергнута: размывает контекст, требует фильтра на каждом экране, тяжелее для backend (filter vs route param).
- **Без префикса `/learn/`** (`/:lang/library`, `/:lang/vocabulary`) — короче URL, но `:lang` оказывается в одном namespace с auth-roots. Конфликт с зарезервированными словами (`/login`, `/admin`) при матчинге роутов. Отвергнуто.
- **Полный URL-state** (фильтры, sort, page в query) — было в первой версии vocabulary spec. Отвергнуто: LingQ не использует, для MVP избыточно, refresh-сохранение фильтров — не критичная фича.
- **`?seg=` для deep-link к сегменту в reader** — было в первой версии reader spec. Отвергнуто: server-stored `reader_positions` дают resume; сценарий «поделиться урок на 42-м предложении» не входит в MVP.
- **Хранение `last_learning_language_code` в localStorage** — клиентское решение без бэкенда. Отвергнуто: при логине с другого устройства язык должен быть тем же, что у пользователя на главном.

## Открытые вопросы

- **Локализованные slug'и для tabs** (`?tab=words` vs `?tab=слова`) — оставляем латинские slug'и. Локализация только в label'ах UI, не в URL.
- **`/admin` под `:lang`?** — нет, admin operations не scoped по learning language. Если admin даёт preview контента — отдельный case, решим при имплементации admin module.

## История

Решение принято после обсуждения 2026-05-01: первая версия UI-спек использовала query-based filter `?lang=...`, но при сравнении с LingQ-стилем (`/ru/learn/pt/web/reader/...`) стало очевидно, что path-сегмент с языком даёт более чистый UX и упрощает backend. Адаптировали LingQ-схему, убрав избыточные сегменты (`/web/`, UI-язык в path) — для self-hosted продукта с одним клиентом и i18next-driven UI это лишнее.
