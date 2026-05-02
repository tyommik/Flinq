# UI spec — страница `Библиотека` (`/learn/:lang/library`)

- Статус: Draft v1
- Дата: 2026-05-01
- Макет-референс: Figma — [Flinq — Library](https://www.figma.com/design/1iDFsUGSEku7QI87AkIBbb/Flinq-%E2%80%94-Library?node-id=1-2), node `1:2` («Library — Desktop 1440»). Локальный экспорт: `docs/ui/library.png`.
- Связано с: ADR-0006 (tech stack), `docs/specs/2026-04-11-mvp-product-alignment-design.md` §3, §10 (форматы импорта, языки), `docs/architecture/2026-04-11-mvp-domain-model.md` §6 (Lesson library)

## 1. Назначение

Главная точка входа после логина. Отвечает за:

- быстрый возврат к недавним урокам (resume);
- обзор всех собственных и shared-уроков;
- запуск импорта нового урока;
- поиск и фильтрацию по библиотеке.

Это «hub» learner-сценария: всё чтение начинается здесь.

## 2. Маршрут и доступ

- Путь: `/learn/:lang/library`, где `:lang ∈ {en, ru, pt}` (decision log §10.1).
- Корневой `/library` или `/` авторизованного пользователя → редирект на `/learn/:lang/library`, где `:lang` берётся из `user_settings.last_learning_language_code` (нужно поле — см. §16).
- Доступ: `learner` (auth обязателен).
- **Query-параметры:**
  - `tab`: `continue` (default) | `lessons` — единственный URL-state.
- **Не URL, а client-state:** search query, фильтры (visibility, language extras), sort, pagination, pageSize. По умолчанию sort = `created_at desc`, page size = 25. Refresh ресетит до default'ов — это сознательно.

## 3. Layout (Figma desktop 1440)

```
┌─ TopBar — 64px ──────────────────────────────────────────────────────────┐
│ Flinq    Библиотека    Словарь                  [👤 АШ ▾]                │
└──────────────────────────────────────────────────────────────────────────┘
─── divider ───────────────────────────────────────────────────────────────
┌─ FilterRow — 78px ───────────────────────────────────────────────────────┐
│ [🔍 Поиск в Библиотеке]    Начальный ●━━━━━━━━ Продвинутый    [+ Импорт]│
└──────────────────────────────────────────────────────────────────────────┘
┌─ SubTabsRow — 53px ──────────────────────────────────────────────────────┐
│ Продолжить изучение | Уроки | (Интерактивные)        Посмотреть все ›   │
└──────────────────────────────────────────────────────────────────────────┘
┌─ CardsRow — 274px ───────────────────────────────────────────────────────┐
│ ‹ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ›                    │
│   │import │ │ cap14 │ │ cap15 │ │ cap16 │ │ cap17 │                      │
│   └───────┘ └───────┘ └───────┘ └───────┘ └───────┘                      │
└──────────────────────────────────────────────────────────────────────────┘
                                                       Посмотреть все ›
```

Размеры из Figma: card 220×250, gap 16px, cover 220×140, meta 110px.

## 4. TopBar (global app shell)

| Элемент Figma | MVP | Комментарий |
|---|---|---|
| Logo `Flinq` (40,16) | ✅ | Кликабельный → `/learn/:lang/library` (текущий язык) |
| **Language picker** (новый) | ✅ | Чип `🇵🇹 Português ▾` рядом с логотипом. Меняет первый сегмент path: `/learn/pt/...` → `/learn/ru/...`. Список — изучаемые языки пользователя из `user_settings`. |
| `Tab/Library (active)` (169,17) | ✅ | Underline `2px`. Ведёт на `/learn/:lang/library` |
| `Слова` tab (283,17) | ✅ | Ведёт на `/learn/:lang/vocabulary` |
| `StreakChip` (🔥 1) | ❌ | Streak вырезан из MVP (decision log §9). Удалить из вёрстки |
| `CoinsChip` (170/100) | ❌ | LingQ-овская монетизация. Self-hosted продукту не нужно. Удалить |
| `AITokensChip` (4339) | ❌ | То же. Если в Phase 2 появятся per-user AI quotas — вернуть как админскую информацию, не gamification |
| `AvatarChip` (АШ + badge `3`) | ⚠️ | Аватар оставляем, badge уведомлений — out of MVP. Dropdown ведёт в Settings/Logout |

> **Решение по top bar:** в MVP остаются Logo, language picker, два таба (Библиотека, Словарь) и Avatar dropdown. Чипы streak/coins/AI tokens из вёрстки убираются. Это — global app shell для всех экранов, не локально на library.

## 5. Tabs верхнего уровня

В Figma на верхнем уровне два таба: `Библиотека` и `Слова`. В MVP global navigation:

- `Библиотека` → `/learn/:lang/library`
- `Словарь` → `/learn/:lang/vocabulary`
- `Повторение` → `/learn/:lang/review`
- `Статистика` → `/learn/:lang/stats`

`:lang` всегда подставляется из текущего активного языка (см. §4 language picker). Все эти разделы scoped по изучаемому языку.

Реализация — отдельный компонент `<AppTopBar>`, не часть страницы Library. Эта спека только фиксирует элементы, видимые в макете.

## 6. FilterRow

### 6.1 Search input

- Размер 420×42 (Figma `1:5`).
- Placeholder: «Поиск в Библиотеке».
- Поле выполняет поиск по `lessons.title` и `lesson_sources.author`. ILIKE с trigram-индексом.
- Debounce 300мс. Запрос — client-state (Zustand store или local state), не URL-параметр.

### 6.2 Import button

- Размер 198×37, primary green.
- Текст: «+ Импортировать урок».
- Поведение: открывает modal импорта с табами форматов:
  - **Текст** (paste textarea + опциональный title).
  - **Файл** (drag-and-drop + file picker, accept `.txt,.md`).
- В Figma также присутствует card «Импорт с YouTube» — см. §8.

### 6.3 Level slider — скрыт в MVP

Slider «Начальный ↔ Продвинутый» (Figma `3:6`) **из вёрстки убирается**. Поля `lessons.difficulty_level` в domain model нет. Возвращаем в Phase 2 вместе с автоматическим estimator'ом (по словарной частотности).

## 7. SubTabsRow

| Sub-tab | URL | Что показывает |
|---|---|---|
| `Продолжить изучение` | `?tab=continue` (default) | Уроки с непустой `reader_positions` пользователя, отсортированные по `last_opened_at desc`. Показывается carousel с навигацией ‹ ›. |
| `Уроки` | `?tab=lessons` | Полный grid всех доступных уроков (own `private` + `shared`), с фильтрами и пагинацией. |
| `Интерактивные уроки` | `?tab=interactive` | **Post-MVP.** В MVP таб скрыт или disabled. Это — будущие уроки с упражнениями (cloze, dictation), вне scope. |

Справа от tabs — `Посмотреть все ›` (Figma `4:11`) — переключает на `?tab=lessons`.

## 8. CardsRow — карточки

### 8.1 Card/Lesson (Figma `7:13`..`7:49`)

Размер 220×250. Структура:

```
┌── Cover 220×140 ──────────┐
│                           │
│     [серия / тема]        │ ← цветная заливка серии
│     CAPÍTULO N            │
│                           │
└───────────────────────────┘
┌── Meta 220×110 ───────────┐
│ Capítulo 14 — Um Mapa     │ ← title, до 2 строк
│ das Índias                │
│                           │
│ ━━━━━━━━━━━━━━━━━━━━━━━   │ ← progress bar 196×4
│ 0% • Новые слова          │ ← coverage %
└───────────────────────────┘
```

**Cover:**
- В макете сейчас захардкоженный шаблон «60 DIAS / PORTUGUÊS / CAPÍTULO N» на жёлтом фоне.
- В MVP cover — **автогенерированный плейсхолдер** на основе `lessons.language_code` + `lessons.title` (палитра по hash от title). Пользовательский upload и `cover_url` — Phase 2.
- Серия / коллекция (`60 DIAS`) — это часть курса (`Course`/`Collection`). В MVP курсы/коллекции **отложены** (см. §13). Cover-плейсхолдер должен корректно работать без них.

**Meta:**
- `Title` — `lessons.title`, max 2 строки + ellipsis.
- `Progress bar` — `lesson_progress.coverage_ratio` (`known_occurrence_count / occurrence_count`).
- `0% • Новые слова` — текст под прогрессом. Для MVP: `{coverage_pct}% • {new_words_count} новых слов`. Источник `new_words_count` — `occurrence_count - known_occurrence_count - tracked_occurrence_count - ignored_occurrence_count`.

Click на card → `/learn/:lang/lessons/$lessonId` (открывает reader, resume по `reader_positions`).

### 8.2 Card/YouTube (Figma `7:6`)

В макете отдельная карточка с иконкой YouTube и текстом «Вставьте ссылку на видео, чтобы создать урок с субтитрами».

> **Решение:** YouTube/URL/audio/video import **не входит в MVP** (decision log §3, формат импорта = только `.txt`/`.md`). Эту карточку в MVP **удаляем** из CardsRow. Импорт делается только через primary button «+ Импортировать урок» в FilterRow.

Если позже захочется promo-card для других форматов — это отдельная конструкция «coming soon», не функциональная.

### 8.3 NavPrev / NavNext (Figma `7:3`, `7:62`)

Стрелки горизонтального carousel'а. Появляются только когда есть items за viewport. Keyboard: `←`/`→` при focus в строке.

## 9. CardsFooter

Footer-блок с правым «Посмотреть все ›». В MVP — duplicate якорной ссылки из subtabs row, можно оставить или убрать (рекомендация — убрать, она дублирует §7).

## 10. View `?tab=lessons` (полный список)

В Figma пока показан только carousel-вариант. Когда пользователь переходит на `?tab=lessons` или жмёт «Посмотреть все», нужен grid:

```
┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐
│ L1 │ │ L2 │ │ L3 │ │ L4 │ │ L5 │
└────┘ └────┘ └────┘ └────┘ └────┘
┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐
│ L6 │ │ L7 │ │ L8 │ │ L9 │ │L10 │
└────┘ └────┘ └────┘ └────┘ └────┘

       ‹ 1 2 3 … 8 ›
```

- 5 колонок при ≥1280px, 4 при 1024–1279, 3 при 768–1023, 2 при 480–767, 1 на mobile.
- Card компонент тот же.
- Доп. фильтр-popover в FilterRow: `visibility` (mine/shared/all), `статус` (`ready` / `processing` / `failed`). Все фильтры — client-state.
- Pagination: 25 per page (default). Page и pageSize — client-state, не URL.
- Sort: `created_at desc` (default, без toggle в MVP).
- Язык НЕ в фильтрах — он уже в path (`/learn/:lang/...`). Бэкенд автоматически фильтрует по `lessons.language_code = :lang`.

## 11. Состояния

### 11.1 Loading
Carousel: 5 skeleton-карточек. Grid: skeleton-сетка.

### 11.2 Empty (новый пользователь)
В области CardsRow:
- Иллюстрация (опционально).
- Заголовок: «У вас пока нет уроков».
- Подзаголовок: «Импортируйте свой первый текст».
- CTA: повтор кнопки «+ Импортировать урок».
- При `?tab=continue` — fallback-текст «Откройте любой урок из библиотеки» + ссылка на `?tab=lessons`.

### 11.3 Empty (фильтры дают 0)
«Ничего не найдено по запросу `{q}`» + «Сбросить фильтры».

### 11.4 Lesson processing
Card с `lessons.status = processing` — показывает spinner поверх cover'а и блокирует click (или ведёт на reader, который показывает full-screen processing state — см. `reader.md` §12.2).

### 11.5 Lesson failed
Card с red border + tooltip с error message + контекстное меню «Retry / Удалить».

## 12. Mobile layout (<md)

- TopBar схлопывается: logo + hamburger + avatar.
- FilterRow: search полноширинный, кнопка «Импорт» = floating action button (FAB).
- SubTabs: горизонтальный scroll.
- Carousel: 1 card visible с peek соседних.
- Grid: 1–2 колонки.

## 13. Связь с backend

API-вызовы делаются с `lang` из path (`/learn/:lang/library`). Бэкенд получает `lang` как query или header, фильтрует автоматически.

- `GET /api/lessons?lang=:lang&tab=continue|lessons&q=...&visibility=...&page=1&pageSize=25` — пагинированный список. URL и параметры идут на API; UI хранит фильтры в client-state, передаёт в запрос.
- `POST /api/lessons` — создание урока из текста (lang в body).
- `POST /api/lessons/import-file` — multipart upload `.txt`/`.md`.
- `DELETE /api/lessons/$id` — архивирование/удаление.
- Backend module owner: `Lesson Library` (architecture overview §7.2).

## 14. Закрытые решения и оставшиеся open questions

**Закрыто:**
- `lessons.level` поля нет, slider скрыт, авто-оценка — Phase 2.
- Cover — авто-плейсхолдер из (`title` hash + `language_code`); пользовательский upload — Phase 2.
- `Course`/`Collection` — отложены, плоский список.
- «Интерактивные уроки» tab — скрыт.
- Sort — `created_at desc`, toggle вернётся в Phase 2.
- Bulk-операции — отложены.

**Остаётся открытым:**
- **`new_words_count` в card meta** — формула `occurrence_count - known - tracked - ignored`. Кешировать ли в `lesson_progress.new_words_count` или считать on-the-fly. Решение к моменту имплементации Lesson Library.

## 15. Не входит в MVP

- YouTube/URL/PDF/EPUB/audio/video импорт (decision log §3).
- Интерактивные уроки (cloze в lesson, dictation, embed exercises).
- Streak / coins / AI token gamification chips.
- Notification badge на avatar.
- Курсы и коллекции (group lessons).
- Shared library marketplace между инсталляциями (decision log §13 non-goals).
- Уровень сложности урока (если откроется в Phase 2).
- Recommendations / next-lesson suggestions (§7.11 спеки — Phase 2+).

## 16. Domain model implications

URL-схема `/learn/:lang/...` требует одной правки domain model:

- **`user_settings.last_learning_language_code TEXT NULL`** — для редиректа `/` → `/learn/:lang/library` после логина. При первом логине новичка заполняется из onboarding (см. `onboarding.md`); далее обновляется при каждой смене языка через TopBar picker.

Альтернатива — выводить из MAX(`last_opened_at`) по `reader_positions`, но это доп. JOIN на каждый redirect и не работает для нового пользователя без открытых уроков.

## 17. Mapping Figma → код

Для последующей реализации:

| Figma frame | React-компонент | Файл |
|---|---|---|
| `TopBar` (1:3) | `<AppTopBar>` | `frontend/src/components/AppTopBar.tsx` (shared) |
| `FilterRow` (3:2) | `<LibraryFilterRow>` | `frontend/src/features/library/FilterRow.tsx` |
| `SubTabsRow` (4:2) | `<LibrarySubTabs>` | `frontend/src/features/library/SubTabs.tsx` |
| `CardsRow` (7:2) | `<LessonCarousel>` | `frontend/src/features/library/LessonCarousel.tsx` |
| `Card/Lesson` (7:13) | `<LessonCard>` | `frontend/src/features/library/LessonCard.tsx` |
| `Cover` (7:14) | `<LessonCover>` | `frontend/src/features/library/LessonCover.tsx` |
| `Progress` (7:21) | `<LessonProgressBar>` | shared component |

Карточки YouTube, чипы StreakChip / CoinsChip / AITokensChip из верстки **не реализуем** в MVP (см. §4, §8.2).
