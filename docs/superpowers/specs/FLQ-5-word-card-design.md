# FLQ-5 — Word Card (Increment 1): design spec

- Дата: 2026-07-07
- Задача: FLQ-5 — Word Card: translation input, dictionary, AI, confidence picker
- Референсы: `docs/ui/word_card.md`, ADR-0005 (статусы/confidence), ADR-0001 (token/phrase),
  ADR-0003 (AI), ADR-0004 (Wiktionary), `docs/architecture/2026-04-11-mvp-domain-model.md` §8
- Макеты Figma: WordCard / Full `node-id=73-2`, WordCard / Collapsed `node-id=77-2`
  (файл `1iDFsUGSEku7QI87AkIBbb`)

## 1. Scope (Инкремент 1)

Единый `<WordCard>` для **token** (фразы отложены) + минимальный vocabulary-бэкенд.

**Входит:**
- Карточка token: collapsed/expanded, 4 layout по статусу (`new / tracked / known / ignored`).
- Ввод собственного перевода (debounced auto-save).
- Объединённые suggestions: user-saved → AI (`✦`) → Wiktionary (`📘`).
- Confidence/status footer.
- Теги (chip-input) и заметки (textarea).
- Backend: таблицы `personal_translations`, `personal_notes`, `item_tags` + vocabulary-API.
- Интеграция в reader: замена `WordCardPlaceholder` и плейсхолдер-чипов в `SentenceView`.

**НЕ входит (следующие инкременты / post-MVP):**
- Phrase-карточка (`phrase_items`, создание фразы из выделения).
- Внешние словари-ссылки (Google Translate / Glosbe / Reverso чипы) и `/settings/dictionaries`.
- TTS (🔊), кнопка «Отчёт», AI-грамматика/примеры/объяснения.

## 2. Модель статуса и confidence (уточнения к ADR-0005)

Диапазон `confidence` в БД остаётся `0..5` — **миграция `token_items` не нужна**
(constraint `ck_token_items_confidence_range` уже `0..5`).

Footer picker (как в макете 73:2): **`🗑  [1] [2] [3] [4]  ✓`**

| Действие в карточке | Результат | Подсветка в тексте |
|---|---|---|
| default (перевод добавлен, уровень не выбран) | `tracked`, `confidence = 0` | **голубой** (как `new`) |
| клик `1..4` | `tracked`, `confidence = 1..4` | **жёлтый** |
| клик `✓` («изучено») | `known` | без подсветки |
| клик `🗑` | `ignored` (мягко, не hard-delete) | без подсветки |

Уточнения относительно ADR-0005:
- **`0` — системный уровень**, руками не выставляется; присваивается при авто-создании item из
  аннотации (перевод/тег/заметка) на `new`-слове. Означает «перевод есть, но в активное
  изучение (1–4) ещё не взято».
- **`5` в ручном picker'е отсутствует.** Значение `5` — только внутренний потолок для SRS
  (FLQ-7). «Выучено» пользователь ставит галочкой `✓` (→ `known`), а не уровнем 5.
- Путь `new → tracked` через ввод перевода даёт `confidence 0` (не `1`, как в таблице
  переходов ADR-0005 §«Переходы»). Явный клик по пилюле стартует с выбранного `1..4`.
  ADR-0005 при реализации получит уточняющую сноску.
- `🗑` = установить `ignored` (word_card.md §11). Hard-delete — только из `/vocabulary` (FLQ-6).

### 2.1 Правило авто-создания item

`personal_translations` / `personal_notes` / `item_tags` привязаны к `(item_kind, item_id)`
(доменная модель §8.5–8.7) — то есть требуют существующей строки item. У `new`-слова строки нет.

Правило: **первая аннотация `new`-слова неявно создаёт `token_item`.**
- ввод перевода / добавление тега / заметки → `tracked`, `confidence = 0`;
- клик по пилюле `1..4` → `tracked`, `confidence = N`;
- `✓` → `known`; `🗑` → `ignored`.

Идемпотентно по `uq_token_items_user_lang_text (user_id, language_code, token_text)`.

## 3. Backend

### 3.1 Новые таблицы (полиморфные по `LearningItemRef`, доменная модель §8.4)

`item_kind` заполняется только значением `'token'` в этом инкременте; `'phrase'` подключится
без миграции. Все три — `owner_user_id` FK `users` `ON DELETE CASCADE`.

**`personal_translations`** (§8.5): `id`, `owner_user_id`, `item_kind`, `item_id`,
`target_language_code`, `translation_text`, `is_primary bool`, `source_type` (`user|ai|dictionary`),
`created_at`.
- Инвариант: не более одного `is_primary = true` на `(owner_user_id, item_kind, item_id,
  target_language_code)` — partial unique index `WHERE is_primary`.

**`personal_notes`** (§8.6): `id`, `owner_user_id`, `item_kind`, `item_id`, `note_text`,
`created_at`, `updated_at`. Одна заметка на item (unique `(owner_user_id, item_kind, item_id)`),
upsert через `PUT`.

**`item_tags`** (§8.7): `id`, `owner_user_id`, `item_kind`, `item_id`, `tag_name`.
- unique `(owner_user_id, item_kind, item_id, tag_name)`.

Одна миграция Alembic `0007_vocabulary_card`.

### 3.2 Endpoints (`/api/vocabulary`, новый роутер под общим `/api` префиксом)

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/lookup?lang={lc}&text={normalized}` | состояние + переводы + заметка + теги + Wiktionary-подсказки |
| `POST` | `/items` | создать `token_item` (kind/text/lang/status/confidence) |
| `PATCH` | `/items/{kind}/{id}` | сменить status/confidence |
| `POST` | `/items/{kind}/{id}/translations` | добавить/промоутнуть перевод |
| `PUT` | `/items/{kind}/{id}/notes` | upsert заметки |
| `POST` | `/items/{kind}/{id}/tags` | добавить тег |
| `DELETE`| `/items/{kind}/{id}/tags/{tag}` | удалить тег |

- `GET /lookup` — единственная точка чтения карточки. Возвращает:
  `{ item_id|null, status ('new'|'tracked'|'known'|'ignored'), confidence|null,
     translations: { primary|null, all: [...] }, note|null, tags: [...],
     dictionary: [ {text, sense?, source:'wiktionary'} ] }`.
  `text` — уже нормализованный (`flinq.core.textnorm.normalize_token`), как ключ к
  occurrences и словарю.
- **AI НЕ входит в `/lookup`.** AI-подсказка для `new`-карточки берётся отдельным вызовом
  существующего `POST /api/ai/translate` (FLQ-3, с `lesson_id`/`segment_id`/`surface_text`
  контекстом и per-user кэшем). Так карточка переиспользует FLQ-3 и работает и вне урока
  (без AI-строки), когда контекста нет.
- Все ручки, создающие/меняющие состояние (`POST /items`, `translations`, `notes`, `tags`),
  применяют правило §2.1 (авто-создание item при отсутствии) через сервис.
- Модуль `vocabulary`: добавить `repo.py`, `service.py`, `schemas.py`, `api` роутер.
  Реюз `flinq.core.textnorm` и `dictionary` lookup (ADR-0004).

### 3.3 Правки reader (FLQ-4) под confidence-зависимую подсветку

- `token-statuses` эндпоинт (reader) должен отдавать не только `status`, но и `confidence`.
- `TokenSpan` красит по паре `(status, confidence)`:
  - `tracked && confidence >= 1` → жёлтый (`--reader-tracked-bg`);
  - `new` **или** `tracked && confidence == 0` → голубой (`--reader-new-bg`);
  - `known` / `ignored` → без подсветки.

## 4. Frontend

### 4.1 Компонент

`<WordCard>` — presentational; данные через TanStack Query `useLookup(lang, text)`.
Мутации (create/patch/translation/note/tag) инвалидируют/патчат кэш `lookup` и (для смены
статуса/уровня) `token-statuses` текущего урока, чтобы подсветка обновлялась мгновенно.

Один внутренний layout, разные wrapper'ы по контексту (word_card.md §2). В этом инкременте —
reader:
- desktop: floating-панель у правого края (overlay) / sidebar; mobile: bottom sheet.
- переиспользуем слот `WordCardPlaceholder` в `ReaderPage`, но заменяем содержимое.

### 4.2 Collapsed vs Expanded

- **Collapsed** (default в reader): header (слово + `✕`), «Тег +», input перевода,
  2 топ-suggestions, **confidence footer**, шеврон `⌄` (expand).
  (Отклонение от макета 77:2, где footer скрыт: следуем word_card.md §3 — статус есть главное
  действие ридера, прятать его за раскрытие не хотим.)
- **Expanded** (73:2): + полный список suggestions, теги (chip-input с автодополнением),
  заметки (textarea), шеврон `⌃` (collapse).
- Toggle persist'ится в memory-store (не в user_settings в этом инкременте).

### 4.3 Layout по статусу (word_card.md §8, ADR-0005)

- `new`: AI-строка первой (если AI включён и есть контекст) → Wiktionary; footer в состоянии
  «уровень не выбран».
- `tracked`: primary-перевод пользователя сверху; подсвечен текущий уровень `1..4`.
- `known`: AI + словарь как подсказка; footer подсвечивает `✓`.
- `ignored`: блок suggestions свёрнут, показано «Ignored» + reactivate (клик `1..4`/`✓`).

### 4.4 Сохранения и hotkeys

- Перевод и заметки — debounced **800ms** + save на blur.
- Теги — по `Enter` / клик по chip удаляет.
- Клик по suggestion `+` — сохранить как primary `personal_translations` (создать/промоутнуть).
- Hotkeys при открытой карточке: `1..4` уровень, `k` → known (`✓`), `i` → ignored (`🗑`),
  `Esc` — закрыть, `Enter` в input — сохранить перевод. (Хоткеев `0` и `5` нет — §2.)

## 5. Состояния и ошибки (word_card.md §12)

- Loading: skeleton; header (слово) показан сразу.
- AI выключен / нет контекста: вместо AI-строки — info-note, без блокирующей ошибки;
  Wiktionary показывается как обычно.
- AI ошибка/timeout: inline-ошибка в блоке suggestions + retry; остальная карточка работает.
- Нет Wiktionary entry: `📘`-подсказки скрыты без ошибки.
- Ошибка сети при сохранении: toast + retry мутации (TanStack Query).

## 6. Тестирование

- **Backend:** переходы статусов (авто-`tracked/0` при аннотации; `1..4`; `✓`→known;
  `🗑`→ignored; reactivate из ignored/known), инвариант единственного primary-перевода,
  агрегация `/lookup` (user + wiktionary), идемпотентность create.
- **Frontend:** 4 layout по статусу, collapsed/expanded, debounced save (перевод/заметка),
  hotkeys `1..4/k/i/Esc`, клик `+` по suggestion, обновление подсветки токена после смены уровня.
- **Integration:** happy-path — клик по `new`-слову в ридере → ввод перевода → уровень 2 →
  токен становится жёлтым; `✓` → подсветка исчезает.

## 7. Открытые вопросы (не блокируют инкремент)

- Точные правила SRS-продвижения по `confidence` (FLQ-7).
- Markdown в заметках — пока plain text.
- Мульти-target primary-переводы — модель поддерживает, UI показывает один target.
