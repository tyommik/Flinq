# FLQ-6 — Vocabulary page (Increment 1): design spec

- Дата: 2026-07-08
- Задача: FLQ-6 — Vocabulary page: table, tabs, filters, bulk actions, inline confidence
- Референсы: `docs/ui/vocabulary.md` (UI-спека, Draft v1 2026-05-01 — с ревизиями ниже),
  ADR-0005 (статусы/confidence), ADR-0007 (URL vs client-state),
  `.superpowers/specs/2026-07-08-wordcard-increment-2-design.md` (FLQ-18),
  доменная модель §8
- Backlog: `backlog/tasks/flq-6 - *.md`

## 1. Scope (Инкремент 1)

**Входит:**
- Страница `/learn/$lang/vocabulary` — таблица личного словаря (token items).
- Табы `Все / Слова / Фразы / К повторению`: работают «Все» и «Слова»
  (сейчас эквивалентны), «Фразы» и «К повторению» — disabled с tooltip
  «Появится позже».
- `GET /api/vocabulary` (пагинированный list с фильтрами) и
  `POST /api/vocabulary/bulk`.
- Поиск (термин + primary-перевод), фильтр-popover, bulk-действия,
  inline confidence picker, пагинация 25/50/100.
- Клик по термину открывает WordCard (реюз FLQ-5/18).
- Empty/error states, мобильный карточный список.
- Пункт «Словарь» в навигации топбара.

**НЕ входит:** phrase items, таб due/Review-кнопка (FLQ-7), импорт/экспорт
(FLQ-14), inline-редактирование перевода, сохранённые фильтры, группировки,
sort по last_reviewed_at.

## 2. Маршрут и state (ревизий к ADR-0007 нет)

- Route `/learn/$lang/vocabulary`, search-параметр `tab=all|words|phrases|due`
  (default `all`) — единственный URL-state, deep-linkable. Валидация: неизвестное
  значение → `all`.
- Всё остальное — client-state в Zustand-store страницы (in-memory, НЕ persist):
  `q`, `statuses` (Set из tracked/known/ignored, default все три),
  `confidenceMin/Max` (1..4, активны только при выбранном tracked),
  `tags: string[]`, `addedPreset` (`7d|30d|all`, default all),
  `sort` (`created_at|text`), `sortDir` (`asc|desc`, default `created_at desc`),
  `page` (с 1), `pageSize` (25|50|100, default 25),
  `selection: Set<item_id>`.
- Смена таба, `q` или любого фильтра → `page = 1`, `selection` очищается.
- `new`-слова на странице отсутствуют по построению (нет строки item).

## 3. Backend

### 3.1 `GET /api/vocabulary`

Query-параметры:

| Параметр | Тип / значения | Default |
|---|---|---|
| `lang` | `en\|ru\|pt` (обязательный) | — |
| `kind` | `token\|all` | `all` |
| `target` | `en\|ru\|pt` — язык primary-перевода в ответе и в поиске | `ru` |
| `status` | повторяемый: `tracked\|known\|ignored` | все три |
| `confidence_min`, `confidence_max` | int 0..5; сужает только tracked-строки — known/ignored (если их статус выбран) проходят фильтр всегда | — |
| `tag` | повторяемый, exact match по `item_tags.tag_name` (AND-семантика) | — |
| `q` | строка ≤128 | — |
| `added_after` | ISO date | — |
| `sort` | `created_at\|text` | `created_at` |
| `sort_dir` | `asc\|desc` | `desc` |
| `page` | int ≥1 | 1 |
| `page_size` | `25\|50\|100` | 25 |

Ответ:

```json
{
  "items": [{
    "item_id": "...", "kind": "token", "text": "abaixaram",
    "status": "tracked", "confidence": 2,
    "primary_translation": {"text": "опустили", "target_language_code": "ru"} ,
    "tags": ["verbs"],
    "pos": "verb",
    "context": "Sacerdotes e fiéis abaixaram a cabeça...",
    "created_at": "..."
  }],
  "total": 1247, "page": 1, "page_size": 25
}
```

- Только items текущего пользователя и `language_code = lang`.
- `q`: `ILIKE %q%` по `token_text` **ИЛИ** по primary-переводу
  (`personal_translations.is_primary AND translation_text ILIKE`) — решение
  open question §11 UI-доки: поиск по переводу включаем.
- `primary_translation` — primary для target-языка пользователя; target
  берётся как в ридере (`ru` в MVP, константа `DEFAULT_TRANSLATION_LANG` —
  передаётся параметром `target`, default `ru`). Нет перевода → `null`.
- `context` — один пример употребления: последний по `lessons.created_at`
  occurrence (`lesson_token_occurrences.normalized_text = token_text`,
  уроки пользователя того же языка) → `lesson_segments.text`. Реализация
  одним запросом (`DISTINCT ON` / lateral), без N+1. Нет occurrence → `null`.
- `pos` — batched lookup `dictionary_entries.part_of_speech` по
  `(language_code, headword = token_text)`; первая entry. Пустой словарь →
  `null`, бейдж не рендерится.
- `total` — count по тем же фильтрам.
- Сервис в `flinq/modules/vocabulary/service.py` (`list_items`), роут в
  существующем роутере `/api/vocabulary`.

### 3.2 `POST /api/vocabulary/bulk`

```json
{"item_ids": ["..."], "action": "set_known|set_ignored|delete|add_tag", "tag_name": "..."}
```

- ≤ **500** id; больше → 422. `tag_name` обязателен для `add_tag` (валидатор).
- Только собственные token-items; чужие/несуществующие id молча пропускаются,
  ответ `{"affected": N}`.
- `set_known` → status=known, confidence=NULL; `set_ignored` аналогично.
- `delete` — hard-delete items + каскад строк `personal_translations`,
  `personal_notes`, `item_tags` тех же items (одним запросом по
  (item_kind, item_id); FK-каскада на полиморфную связь нет — чистим явно).
- `add_tag` — insert с `on_conflict_do_nothing` (идемпотентно, как add_tag FLQ-5).
- Всё в одной транзакции.

### 3.3 Inline-смена статуса

Существующий `PATCH /api/vocabulary/items/{kind}/{id}` (FLQ-5) — без изменений.

## 4. Inline confidence picker (ревизия §8 UI-доки)

UI-док писался до FLQ-5 §2 и требует пилюли `0..5`. Ревизия: **единый виджет
со WordCard — `🗑 [1][2][3][4] ✓`**:
- клик `1..4` → tracked/N; `✓` → known; `🗑` → ignored (не delete);
- при `confidence = 0` ни одна пилюля не подсвечена («добавлено, не в
  активном изучении» — согласовано с подсветкой ридера);
- ручных `0` и `5` нет (0 — системный, 5 — потолок SRS, FLQ-7);
- один и тот же компонент (вынести пикер из WordCard в
  `features/vocabulary/ConfidencePicker.tsx` или общий модуль и реюзнуть в
  WordCard — footer WordCard не должен дублировать логику).
- `docs/ui/vocabulary.md` §8 получает пометку о ревизии (см. §8 этой спеки).

## 5. Frontend

### 5.1 Структура

`frontend/src/features/vocabulary/`:
- `VocabularyPage.tsx` — layout: заголовок «Словарь», табы, toolbar, таблица
  /карточки, пагинация;
- `vocabularyStore.ts` — Zustand (state §2);
- `useVocabularyQuery.ts` — TanStack Query поверх `GET /api/vocabulary`
  (queryKey включает lang+tab+все фильтры), мутации bulk и patch
  (инвалидация списка);
- `VocabularyTable.tsx` (+ строка), `VocabularyCardList.tsx` (mobile),
  `FilterPopover.tsx`, `BulkActionsMenu.tsx`, `ConfidencePicker.tsx`;
- route в `routeTree.ts` + ссылка «Словарь» в `AppTopBar` рядом с
  «Библиотека».

### 5.2 Таблица (desktop ≥md)

Колонки: `☐` / Термин (текст крупно; ниже чипы: POS если есть + теги) /
Перевод (флажок target + текст primary или серое «—») / Контекст (~80 симв.
с ellipsis, курсив, в кавычках; пусто → «—») / Пикер.
- Чекбокс в шапке = select all на текущей странице; selection живёт в store.
- Клик по термину → WordCard overlay (см. §5.4). Клик по строке вне
  интерактивных элементов — ничего.
- Пагинация снизу: ‹ 1 2 … N › + «Всего: N», селектор 25/50/100 в toolbar.

### 5.3 Toolbar

- Поиск: input с иконкой, debounce **300ms**.
- Фильтры (popover): чекбоксы статусов; range confidence 1–4 (disabled если
  tracked не выбран); тег chip-input (автодополнение по тегам из текущей
  выдачи — отдельного endpoint'а тегов в MVP нет); пресеты даты
  «7 дней / 30 дней / Всё время». Кнопка «Сбросить».
- Bulk actions (dropdown, активен при selection>0): «Отметить known»,
  «Отметить ignored», «Добавить тег…» (inline-инпут), «Удалить из словаря»
  (destructive, confirm-диалог «Удалить N слов? Переводы, заметки и теги
  будут удалены») . После успеха — сброс selection, инвалидация списка,
  для delete — toast «Удалено N».

### 5.4 WordCard на странице словаря

- Реюз `<WordCard>`: prop `lessonId` становится опциональным
  (`lessonId?: string | null`); при `null` мутации не инвалидируют
  `['reader-statuses', ...]`, `lesson_id` в AI-запрос не передаётся.
- `sentenceText = null` (контекста урока нет) → AI-запрос с фолбэком на слово,
  как уже реализовано в FLQ-18.
- После закрытия карточки список инвалидируется (статус/перевод могли
  измениться).

### 5.5 Состояния и mobile

- Loading: skeleton 5 строк; табы и toolbar активны.
- Empty (словарь пуст, фильтры default): «В словаре пока пусто» +
  «Начните с импорта урока — нажимайте на слова в reader, и они появятся
  здесь» + CTA «Перейти в библиотеку» → `/learn/$lang/library`.
- Empty (фильтры/поиск дали 0): «Ничего не найдено по текущим фильтрам» +
  «Сбросить фильтры».
- Error: inline alert над таблицей + retry.
- Mobile (<md): карточный список по §10 UI-доки — термин + перевод, чипы,
  контекст, снизу пикер `🗑 [1-4] ✓`; чекбокс выбора в углу карточки;
  toolbar схлопывается (иконки поиска/фильтра, меню действий).

## 6. Тестирование

- **Backend:** `GET /api/vocabulary` — изоляция по владельцу и lang; фильтры
  status/confidence/tag/дата; поиск по термину и по переводу; сортировки;
  пагинация и total; context-подзапрос (occurrence есть/нет); pos lookup;
  bulk: все 4 действия, `affected`, лимит 500 → 422, чужие id пропущены,
  delete каскадит переводы/заметки/теги, add_tag идемпотентен.
- **Frontend:** рендер строк из мок-ответа; picker → PATCH + оптимистичное
  обновление/инвалидация; selection + bulk с confirm; поиск с debounce;
  фильтры сбрасывают page; empty states оба; disabled-табы; переход по CTA.
- **Integration (смоук):** живой браузер — открыть словарь после чтения
  урока, сменить уровень пикером (строка и ридер согласованы), bulk-delete
  с подтверждением, поиск по переводу.

## 7. Открытые вопросы (не блокируют)

- Автодополнение тегов по всем тегам пользователя (отдельный endpoint) —
  при необходимости в FLQ-6.x.
- Отдельный count-бейдж для «К повторению» — вместе с FLQ-7.
- Sort по колонкам кликом в заголовке — пока только через toolbar.

## 8. Ревизии других документов

- `docs/ui/vocabulary.md` §8: пикер `0..5` заменяется на `🗑 [1][2][3][4] ✓`
  (решение FLQ-5 §2); §4-кнопки Импорт/Экспорт/Review и табы Фразы/due
  помечаются как «после FLQ-7/FLQ-14»; поиск по переводу — принято.
  Правка вносится коммитом в рамках FLQ-6.
