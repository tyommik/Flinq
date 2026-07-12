# UI spec — страница `Словарь` (`/vocabulary`)

- Статус: Draft v1
- Дата: 2026-05-01
- Макет-референс: `docs/ui/vocabulary_top.png` (LingQ Vocabulary, источник вдохновения)
- Связано с: ADR-0001 (token/phrase, без леммы), ADR-0005 (статусы и confidence 0..5), `docs/architecture/2026-04-11-mvp-domain-model.md` §8, `docs/specs/2026-04-11-mvp-product-alignment-design.md` §9

## 1. Назначение

Личный словарь пользователя — список всех его learning items (token + phrase) со статусом `tracked`, `known`, `ignored`. Страница даёт:

- обзор всей сохранённой лексики;
- быстрый поиск, фильтры и сортировку;
- inline-управление статусом и confidence без открытия карточки;
- запуск review-сессии и импорт/экспорт словаря;
- bulk-операции через чекбоксы.

`new` items на этой странице **не отображаются** — `new` существует только как вычисляемое состояние occurrence в reader (см. domain model §2.2).

## 2. Маршрут и доступ

- Путь: `/learn/:lang/vocabulary`, где `:lang ∈ {en, ru, pt}` (decision log §10.1). Изучаемый язык — в path, не в фильтре.
- Доступ: `learner` (требуется auth).
- **Query-параметры:**
  - `tab`: `all` (default) | `words` | `phrases` | `due` — единственный URL-state, deep-linkable.
- **Не URL, а client-state** (Zustand store страницы): `status` фильтр, search query, sort, page, pageSize. Default'ы: status = все три, sort = `created_at desc`, pageSize = 25.

## 3. Layout (desktop)

```
┌─ App shell (header + sidebar — описано отдельно) ─────────────────┐
│                                                                   │
│  ┌─ Page header ─────────────────────────────────────────────────┐│
│  │  Словарь                          [Импорт] [Экспорт] [Review]││
│  └───────────────────────────────────────────────────────────────┘│
│                                                                   │
│  ┌─ Tabs ────────────────────────────────────────────────────────┐│
│  │ ● Все   ○ Слова   ○ Фразы   ○ К повторению (12)              ││
│  └───────────────────────────────────────────────────────────────┘│
│                                                                   │
│  ┌─ Toolbar ─────────────────────────────────────────────────────┐│
│  │  [🔍 поиск]   [Фильтры ▾]   [Bulk actions ▾]    [25 / стр ▾] ││
│  └───────────────────────────────────────────────────────────────┘│
│                                                                   │
│  ┌─ Table ───────────────────────────────────────────────────────┐│
│  │ ☐  Термин          Перевод       Контекст            Статус  ││
│  │ ☐  abacaxi         🇷🇺 ананас     "Eles tomam suco…" […✓]    ││
│  │    [сущ.]                                                     ││
│  │ ☐  abaixaram       🇷🇺 опустили   "Sacerdotes e…"    [..4..] ││
│  │    [глаг.] [eles]                                             ││
│  │ …                                                             ││
│  └───────────────────────────────────────────────────────────────┘│
│                                                                   │
│  Pagination: ‹ 1 2 3 … 12 ›                       Всего: 1 247 шт ││
└───────────────────────────────────────────────────────────────────┘
```

## 4. Page header

> **Ревизия 2026-07-08 (FLQ-6):** кнопки Импорт/Экспорт появятся с FLQ-14,
> Review — с FLQ-7; в текущей реализации header содержит только заголовок.
> Табы «Фразы» и «К повторению» (§5) — disabled с tooltip «Появится позже»
> до phrase-инкремента и FLQ-7 соответственно. Поиск по переводу (§6.1
> open question) — принято и реализовано.

- **Заголовок:** «Словарь» (i18n: `vocabulary.page.title`).
- **Кнопки справа:**
  - **Импорт** (icon + label) — открывает modal импорта пользовательского словаря (CSV/JSON). MVP: спека импорта = open question, см. §11.
  - **Экспорт** — скачивает JSON со всеми items (формат — см. backend export endpoint).
  - **Review** (primary) — переводит на `/review` с фильтром по текущим табам/языкам (если активна вкладка `due` — стартует именно очередь due items).

## 5. Tabs

| Таб | Что показывает | Backend-фильтр |
|---|---|---|
| `Все` | tokens + phrases, любой статус из {tracked, known, ignored} | без фильтра по `item_kind`, `status IN (...)` из URL |
| `Слова` | только token_items | `item_kind = token` |
| `Фразы` | только phrase_items | `item_kind = phrase` |
| `К повторению` | только items с `review_items.due_at <= now()` | JOIN `review_items` ON active=true AND due_at<=now() |

Бейдж с числом (`К повторению (12)`) обновляется по реальному count'у. Остальные табы без бейджей в MVP.

## 6. Toolbar

### 6.1 Поиск

- Input с иконкой 🔍.
- Поиск по `token_text` / `phrase_text` (ILIKE, начало строки приоритет — реализуется через PG trigram или простой ILIKE с двумя SQL-pattern'ами).
- Доп. поиск по `personal_translations.translation_text` — open question §11.
- Debounce 300мс. Запрос — client-state, не URL.

### 6.2 Фильтры (popover)

Все фильтры — **client-state** (Zustand store страницы), не URL.

- **Статус**: чекбоксы `tracked / known / ignored` (default — все три).
- **Confidence**: range slider `0..5`, активен только если в статусе выбран `tracked`.
- **Тег**: chip-input с автодополнением по `item_tags`.
- **Дата добавления**: presets «За 7 дней / 30 дней / Всё время» + custom range.

> Язык **не** в фильтрах — он уже в path (`/learn/:lang/vocabulary`). Бэкенд автоматически фильтрует `token_items.language_code = :lang`.

### 6.3 Bulk actions (dropdown)

Активен только при выбранных чекбоксах. Действия:

- **Отметить как known** → переводит выбранные `tracked`/`ignored` в `known`. Подтверждение для >50 items.
- **Отметить как ignored**.
- **Удалить из словаря** → hard-delete `token_items` / `phrase_items` (с подтверждением). Каскадно удаляет переводы, заметки, теги, review_items.
- **Добавить тег** → текстовое поле с автодополнением.

### 6.4 Pagination size

`25` | `50` | `100`. Default `25` (как в макете LingQ).

## 7. Table — состав колонок

| Колонка | Содержимое | Источник |
|---|---|---|
| ☐ | Чекбокс bulk-select | UI state |
| Термин | `token_text` / `phrase_text` крупно; ниже — chips: часть речи, теги, для глагола — форма (если есть в metadata) | `token_items.token_text` + `item_tags` + (опционально) Wiktionary lookup для POS |
| Перевод | Флажок `target_language_code` + `personal_translations.translation_text` (primary). Если перевода нет — placeholder «—» серым | `personal_translations` WHERE `is_primary=true` |
| Контекст | Один пример употребления (~80 символов с ellipsis), курсивом, в кавычках | `lesson_token_occurrences` → `lesson_segments.text` (последнее occurrence или указанное `created_from_occurrence_id`) |
| Статус | Inline confidence picker (см. §8) | `token_items.status` + `confidence` |

### 7.1 Бейджи под термином

- **Часть речи** (`сущ.`, `глаг.`, `прил.`, …) — из Wiktionary `dictionary_entries.part_of_speech` lookup'ом по `(language_code, headword=token_text)`. Если нет — не показываем.
- **Пользовательские теги** (`item_tags.tag_name`).
- **Грамм. формы** (`indicativo pretérito perfeito`, `eles/ellas/vocês`) — берётся из Wiktionary, **не в MVP** (см. §11).

В MVP допустимо показывать только теги; POS — если уже есть в локальном словаре, то да, иначе пусто.

## 8. Inline confidence picker (колонка «Статус»)

> **Ревизия 2026-07-08 (FLQ-6, по решению FLQ-5 §2):** пикер приведён к единому
> виджету со WordCard — `🗑 [1] [2] [3] [4] ✓`. `5` — внутренний потолок SRS (FLQ-7).
> Описание ниже соответствует реализации.
>
> **Ревизия 2026-07-12:** авто-создание item (первое неявное действие на `new`
> слове) теперь ставит `confidence=1`, а не `0` — по ADR-0005 §«Переходы»
> (`new → tracked` стартует с `1`), чтобы слово сразу подсвечивалось жёлтым
> в reader. Уровень `0` руками не ставится и остаётся только как floor
> SRS-понижений и в legacy-данных; при `confidence=0` ни одна пилюля не подсвечена.

```
[🗑]  [1] [2] [3] [4]  [✓]
```

- **4 пилюли `1..4`** — клик устанавливает `status=tracked` и `confidence=N`. Текущая выделена. На hover — tooltip «Уверенность N/4».
- **`✓`** — клик переводит item в `status=known` (`confidence=NULL`).
- **`🗑` (корзина)** — переводит item в `status=ignored`. Не удаляет запись из БД (это делается через bulk → «Удалить»).
- Общий компонент `frontend/src/components/ConfidencePicker.tsx` (реюз в WordCard и на mobile-карточках; отдельного mobile-dropdown нет).

> **Open question §11**: показывать ли отдельную кнопку «Ignore» в строке (помимо `🗑`). Альтернатива — `🗑` маршрутизирует в ignored, а удаление только через bulk. **Рекомендация для MVP: иконка корзины = ignored**, hard-delete доступен только через bulk action с явным подтверждением.

## 9. Состояния

### 9.1 Loading

- Skeleton: 5 строк таблицы с серыми блоками вместо контента. Toolbar и табы остаются интерактивными.

### 9.2 Empty (пользователь только зарегистрировался)

- Большой empty state в области таблицы:
  - Заголовок: «В словаре пока пусто».
  - Подзаголовок: «Начните с импорта урока — нажимайте на слова в reader, и они появятся здесь».
  - CTA: «Перейти в библиотеку» → `/library`.

### 9.3 Empty (фильтры дают 0 результатов)

- Вместо предыдущего варианта: «Ничего не найдено по текущим фильтрам» + кнопка «Сбросить фильтры».

### 9.4 Error

- Inline alert над таблицей с retry-кнопкой; при retry перезапускается TanStack Query.

### 9.5 Offline / kill-switch для AI

- Не влияет на этот экран (словарь работает локально).

## 10. Mobile layout (<md)

- Tabs остаются (горизонтальный scroll).
- Toolbar схлопывается: иконка фильтра + иконка поиска (раскрывается в полноширинный input) + меню «Действия».
- Таблица превращается в **карточный список**:

```
┌───────────────────────────────────────┐
│ abaixaram          🇷🇺 опустили        │
│ [глаг.] [eles]                        │
│ "Sacerdotes e fiéis abaixaram…"       │
│                                       │
│ [🗑]   ●●●●○○ confidence 4   [✓]      │
└───────────────────────────────────────┘
```

- Confidence picker на mobile — тот же общий виджет `🗑 [1][2][3][4] ✓` (см. §8, ревизия 2026-07-08); идея кликабельных точек `0..5` без чисел отброшена вместе с уровнями `0`/`5` в UI.

## 11. Open questions

- **Поиск по переводу** — включать или только по термину?
- **POS / грамм. формы в бейджах** — зависят от готовности Wiktionary lookup'а в MVP. Если не готово к старту — бейджи только пользовательских тегов.
- **Bulk size limit** — лимит на количество items в одной bulk-операции (для UX и для нагрузки на DB). Предлагаю мягкий лимит 500 + warning.
- **Импорт пользовательского словаря** — формат и спека отдельной страницы/модалки. CSV или JSON или оба? Mapping колонок? — отдельный документ.
- **Sort by `last_reviewed_at`** — требует JOIN с `review_items`; решить, надо ли в MVP.
- **Phrase rendering в колонке «Контекст»** — для phrase_item показывать сам урок-источник + bracketing фразы? Или просто текст сегмента?
- **Виджет confidence: 6 пилюль vs slider** — пилюли занимают больше места. Альтернатива — slider `0..5` со step=1, но он хуже доступен с клавиатуры. Рекомендация — пилюли.
- **Отображение `confidence=0`** — `0` означает «только что добавлено, ни одного review». Стоит ли визуально отличать его от пустого `tracked`? Скорее нет — оставляем как обычную пилюлю «0».

## 12. Связь с backend

- **Endpoint:** `GET /vocabulary` — пагинированный list, query-параметры из §2.
- **Endpoint:** `PATCH /vocabulary/{item_kind}/{item_id}` — обновление статуса/confidence из inline picker.
- **Endpoint:** `POST /vocabulary/bulk` — bulk action (`{ ids: [...], action: 'set_known' | 'set_ignored' | 'delete' | 'add_tag', payload: ... }`).
- **Endpoint:** `GET /vocabulary/export` — JSON dump.
- **Endpoint:** `POST /vocabulary/import` — импорт.
- Backend-модули: `Vocabulary` (основной) + `Review Engine` (для таба `due` и счётчика).

## 13. Не входит в MVP

- Группировка по lessons / тегам / коллекциям (только плоский список).
- Inline-редактирование перевода (только через карточку слова).
- Перетаскивание / reorder.
- Сохранённые «views» (конфигурации фильтров).
- Phrase mining suggestions.
- AI-предложения для перевода/тегов на этой странице (AI вызывается только в reader для контекстного перевода — decision log §5).
