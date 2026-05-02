# UI spec — страница `Reader` (`/lessons/$lessonId`)

- Статус: Draft v1
- Дата: 2026-05-01
- Макет-референс: `docs/ui/reader_no_sidebar.png` (sentence mode), `docs/ui/reader_w_sidebar.png` (page mode со сайдбаром карточки)
- Связано с: ADR-0005 (статусы, confidence, подсветка), `docs/architecture/2026-04-11-mvp-architecture-overview.md` §7.3, §10.2, `docs/specs/2026-04-11-mvp-product-alignment-design.md` §9, ADR-0001 (token/phrase)
- Связан со спекой карточки: `docs/ui/word_card.md`

## 1. Назначение

Reader — основной экран продукта. Отвечает за:

- отображение текста урока с подсветкой статусов (`new` / `tracked`);
- per-page bulk-known переход при нажатии «next»;
- клик по слову/фразе → открытие карточки;
- запуск review-сессии из контекста текущего урока;
- сохранение reader-position между сессиями.

## 2. Маршрут и доступ

- Путь: `/learn/:lang/lessons/:lessonId`, где `:lang ∈ {en, ru, pt}` (decision log §10.1).
- Доступ: `learner` (любой урок со `visibility=shared` или собственный `private`).
- **Без query-параметров.** View mode и текущий segment — client-state и серверная сессия (`reader_positions`), не URL.
- Resume: при заходе бэкенд отдаёт `reader_positions.current_segment_id` пользователя.

## 3. Два view mode

В MVP поддерживаем два режима, переключаемых из bottom toolbar:

| Mode | Что показывает | Когда удобен |
|---|---|---|
| `page` | Длинный текст: ~200–400 слов, скролл, опциональный side panel с активной карточкой | Чтение длинных текстов, обзор |
| `sentence` | Один сегмент по центру (sentence или paragraph), крупно, без сайдбара. Под сегментом — мини-список tracked items этого сегмента | Глубокий разбор фрагмента, прослушивание |

Текущий mode — **client-state** (Zustand reader store), default берётся из `user_settings.reader_view_mode` при открытии. Toggle меняет state и persist'ится обратно в settings (debounced).

> **Решение по page size:** в `page` mode страница = ~250 слов (±50 для выравнивания по границе предложения). Точное число — open question в decision log §11, рекомендация: 250 слов как начальный default, конфигурируется через user settings.

> **Решение по segment unit в `sentence` mode:** базовая единица — `sentence`. Переключение на `paragraph` — open question, в MVP только sentence.

## 4. Layout — `sentence` mode (no_sidebar)

```
┌─ Top bar ────────────────────────────────────────────────────────┐
│ [☰]   ●━━━━━━━━━━━━━━━━━━━━            [Aa] [⋯] [→| sidebar]    │
└──────────────────────────────────────────────────────────────────┘
        progress bar (по lesson_segments)

       ┌──────────── Sentence area ────────────┐
       │                                       │
       │            [🔊 sentence]              │
       │                                       │
       │   O Senhor Proctor e o Senhor Fogg,   │
‹ prev │   revólveres em punho, correram para  │ next ›
       │   a frente do trem, onde as explosões │
       │                                       │
       │      [Показать перевод ▾]             │
       │                                       │
       │   ┌─ Vocab из этого сегмента ────┐    │
       │   │ ④  revólveres 🔊  револьверы  │    │
       │   │ ②  em punho   🔊  в руке      │    │
       │   │ ③  correram   🔊  побежали    │    │
       │   └──────────────────────────────┘    │
       └───────────────────────────────────────┘

┌─ Bottom toolbar ────────────────────────────────────────────────┐
│   [Show full page]    [Review words from sentence]              │
└─────────────────────────────────────────────────────────────────┘
```

**Адаптация под MVP** (что вырезано из LingQ-макета):
- 🔊 sentence audio — **post-MVP** (TTS вне MVP, decision log §10.2). Кнопка скрыта или показывает «Скоро».
- «Сгенерировать аудио», «Упрощенный (ИИ)» из bottom toolbar — **post-MVP** (AI вне контекстного перевода — Phase 2).
- Streak / coin / gem из top bar — **вырезаем** (decision log §9: streak вне MVP).
- Avatar dropdown — это global app shell, не reader.

В bottom toolbar MVP оставляем:
- **Show full page** / **Show sentence by sentence** (переключение mode).
- **Review words from sentence** → запускает review с фильтром по `lesson_id` + текущему сегменту.

## 5. Layout — `page` mode

Аналогичный top bar и bottom toolbar, но:

- Текст урока скроллится в основной колонке (max-width ~720px).
- Опциональный right sidebar (toggle через [→| ] в top bar):
  - **Скрыт по default:** карточка слова открывается как **bottom sheet** (mobile) или **floating panel** справа (desktop, если viewport позволяет).
  - **Показан:** карточка живёт прямо в sidebar, без overlay над текстом. Удобно при долгом изучении одного урока.
- Внизу страницы кнопка **«Next page»** — триггерит per-page bulk-known (см. §6).
- Слева кнопка **«Prev page»** — без bulk-эффекта, просто навигация.

## 6. Подсветка токенов в тексте

По ADR-0005:

| Статус | Стиль |
|---|---|
| `new` | **Бледно-голубой fill** (`bg-sky-100` / `--reader-new-bg`). Cursor pointer на hover. |
| `tracked` | **Жёлтый fill** (`bg-yellow-200` / `--reader-tracked-bg`). В MVP равномерный — confidence-gradient отложен (open question ADR-0005). |
| `known` | Без выделения (как обычный текст). |
| `ignored` | Без выделения. Опциональный dotted-underline — open question; в MVP не показываем. |

> **Deviation от макета LingQ.** В `reader_no_sidebar.png` `new` слова показаны dotted-underline. Мы используем бледно-голубой fill согласно ADR-0005 — это решение зафиксировано, не меняем.

**Phrase highlighting:** если token входит в сохранённую `phrase_item`, статус фразы доминирует над статусом отдельного токена. Граница фразы рендерится одним непрерывным span'ом без gap'ов между токенами.

## 7. Top bar — состав

| Элемент | Назначение | MVP |
|---|---|---|
| `[☰]` | Сворачивание/раскрытие global app sidebar (Library, Vocabulary, Stats…) | да |
| Progress bar | Заполнение по `lesson_progress.coverage_ratio` или по позиции в segments | да (по позиции, coverage в tooltip) |
| `[Aa]` | Popover с настройками шрифта: размер (3 шага), line-height, serif/sans toggle | да |
| `[⋯]` | Меню урока: «Открыть в библиотеке», «Скопировать ссылку», «Метаданные», «Архивировать» | да (минимум — link to library + archive) |
| `[→\|]` | Toggle right sidebar (только в `page` mode) | да |
| `[X]` (на reader_no_sidebar) | Закрыть reader → вернуться на `/library` | да |

## 8. Vocab list под сегментом (sentence mode)

Под основным предложением показываем горизонтальные мини-карточки tracked items из этого сегмента (см. макет, нижний блок).

Состав карточки:
- Confidence indicator: круг с числом `0..5` (цвет — yellow scale; для `0` пилюля без fill).
- Surface text слова/фразы.
- 🔊 (post-MVP).
- Перевод (primary `personal_translations.translation_text`).

Действия:
- Click на карточку → открытие основной word card (см. `word_card.md`).
- В MVP **inline-редактирование confidence из этого мини-блока не поддерживается** (только через основную карточку), чтобы не дублировать контролы.

`new` слова в этот блок не попадают (нет персистентной записи). `known`/`ignored` тоже не попадают — это блок «что я учу здесь».

## 9. Per-page bulk-known (только `page` mode)

ADR-0005 §«Переходы»:

- Нажатие **«Next page»** переводит **все `new` occurrences текущей страницы** в `known`.
- `tracked`/`known`/`ignored` не затрагиваются.
- Backend создаёт `bulk_actions` запись с `payload_json` со списком созданных `token_items`.

**UX обратимости:**
- После клика «Next page» в нижней части экрана появляется **toast** с текстом «N слов помечены как known» и кнопкой **«Отменить»** (live ~6 секунд).
- Toast также повторяется в области footer как persistent **«Отменить bulk-known»** на текущей странице (до перехода ещё дальше).
- Отмена — POST `/reader/bulk-actions/{id}/undo`.

В `sentence` mode bulk-known **не выполняется** при «next sentence» — только клавиатурное действие или специальная кнопка (не в MVP).

## 10. Hotkeys

В MVP минимальный набор:

| Клавиша | Действие |
|---|---|
| `←` / `→` | prev / next page (или sentence) |
| `Esc` | закрыть карточку слова или закрыть reader |
| `f` | toggle font popover |
| `s` | toggle sidebar |
| `m` | toggle view mode (page ↔ sentence) |
| `r` | start review words from current page/sentence |
| `1`..`5` | при открытой карточке — установить confidence |
| `k` | при открытой карточке — mark known |
| `i` | при открытой карточке — mark ignored |
| `Ctrl+Z` | undo последнего bulk-known (если ещё доступно) |

Полный список фиксируется отдельным мини-документом — open question.

## 11. Phrase selection

- **Desktop:** click + drag по соседним токенам, либо `Shift+click` на второй токен от уже выделенного. Появляется флоат-кнопка «Save as phrase» → создаёт `phrase_item` со статусом `tracked` confidence `1`.
- **Mobile:** long-press + drag по соседним токенам. Поведение native iOS/Android selection не используем — нужен кастомный selection over span'ов.

После создания phrase: подсветка немедленно обновляется (через TanStack Query invalidate).

## 12. Состояния

### 12.1 Loading lesson
Skeleton: серый блок с пульсацией на месте текста. Top bar и bottom toolbar активны.

### 12.2 Lesson `processing`
Урок ещё обрабатывается worker'ом (segmentation, tokenization). Показываем full-screen state: «Урок готовится» + spinner + estimated time. Polling `GET /lessons/$id` каждые 2 секунды.

### 12.3 Lesson `failed`
Full-screen error: причина + кнопки «Retry» (re-trigger import job) и «Удалить урок».

### 12.4 Network error при action
Inline toast «Не удалось сохранить» + retry. Optimistic update откатывается.

## 13. Mobile layout (<md)

- Top bar схлопывается: `[☰] progress [⋯]`, [Aa] переезжает в `[⋯]` меню.
- Side arrows навигации заменяются swipe gesture (left/right).
- Sidebar toggle недоступен — карточка всегда как bottom sheet.
- Bottom toolbar: только два главных действия (toggle mode + review), остальное — в `[⋯]`.

## 14. Связь с backend

- `GET /lessons/$id` — метаданные урока + текущая позиция.
- `GET /lessons/$id/page?seg=$segId&size=N` — content страницы / сегмента с pre-resolved статусами токенов и подсвеченными phrase occurrences для текущего пользователя.
- `GET /lessons/$id/sentence?seg=$segId` — один сегмент + связанные tracked items (для vocab list).
- `POST /reader/positions` — обновление `reader_positions` (debounced).
- `POST /reader/bulk-actions` — bulk-known.
- `POST /reader/bulk-actions/$id/undo` — отмена.
- Карточка слова — отдельные endpoints (см. `word_card.md` §10).

Backend module owner: `Reader State` (см. architecture overview §7.3).

## 15. Open questions

- **Page size:** 250 слов default — нужно валидировать на реальных текстах. Конфигурируемое в settings.
- **Segment granularity в sentence mode:** sentence vs paragraph toggle — отложен.
- **Confidence gradient в подсветке `tracked`:** в MVP равномерный жёлтый.
- **Phrase auto-highlight в других уроках:** open question decision log §11.
- **Audio / TTS / AI simplify:** post-MVP, заглушки скрыты.
- **Hotkey conflicts:** проверка на mac/windows (Ctrl vs Cmd).
- **Reader font choice:** один sans-serif вариант в MVP или давать выбор пользователю.

## 16. Не входит в MVP

- TTS (генерация аудио, sentence audio play, audio sync).
- AI-симплификация текста.
- Bilingual line-by-line view (§7.4 спеки — Phase 2).
- Hidden translation mode.
- Offline cache.
- Phrase auto-matching across lessons.
- Bulk-ignored на странице.
- Image translation для встраиваемых картинок.