# UI spec — карточка learning item (Word / Phrase Card)

- Статус: Draft v1
- Дата: 2026-05-01
- Макет-референс: `docs/ui/new_words_card.png` (expanded), `docs/ui/new_words_card_collapsed.png` (collapsed), правый блок в `docs/ui/reader_w_sidebar.png`
- Связано с: ADR-0005 (статусы, confidence, состав карточки по статусам), ADR-0001 (token/phrase), ADR-0003 (LLM provider), ADR-0004 (Wiktionary), `docs/architecture/2026-04-11-mvp-domain-model.md` §8

## 1. Назначение

Карточка — основной интерактивный элемент reader'а и страницы Vocabulary. Открывается при клике по token / phrase и позволяет:

- увидеть переводы (пользовательский, словарный, AI);
- ввести/отредактировать собственный перевод;
- управлять статусом (`new` → `tracked` / `known` / `ignored` и обратные revert'ы);
- управлять confidence для `tracked` (UI-пикер экспонирует уровни `1..4`; модель хранения — `0..5` по ADR-0005);
- ставить теги и заметки.

Карточка — **единое UI-решение** для token и phrase. Различия в данных, не в форме.

## 2. Размещение

| Контекст | Размещение |
|---|---|
| Reader desktop, sidebar = ON | В right sidebar (рядом с текстом) |
| Reader desktop, sidebar = OFF | Floating panel у правого края (overlay), с диммингом текста |
| Reader mobile | Bottom sheet, swipe-down для закрытия |
| `/vocabulary` desktop | Modal по центру (overlay) |
| `/vocabulary` mobile | Bottom sheet |

Один компонент, разные wrapper'ы. Внутренний layout одинаковый — это упрощает реализацию.

## 3. Два режима высоты

По макету LingQ карточка имеет **collapsed** и **expanded** состояния (см. `_collapsed.png` vs `.png`):

| Mode | Что показано | Когда |
|---|---|---|
| Collapsed | Header, поле «новый перевод», 2 топ-suggestions, confidence picker | По default в reader (не закрывает текст) |
| Expanded | Полный набор: + словари, все suggestions, примеры, заметки, теги | По клику на chevron / при открытии из `/vocabulary` |

Toggle через chevron `▽`/`△` в нижней части карточки. Состояние persist'ится в `user_settings.word_card_default_mode` или просто в memory store.

## 4. Структура (expanded mode)

```
┌─────────────────────────────────────────────┐
│ 🔊  cada vez                          [✕]   │
│ Тег+                                        │
├─────────────────────────────────────────────┤
│ Сохранённый перевод               [△]       │
│ ┌────────────────────────────────────────┐  │
│ │ Введите новый перевод здесь          🇷🇺│  │
│ └────────────────────────────────────────┘  │
│                                             │
│ Словари                       Настроить >   │
│ [Wiktionary] [Glosbe (popup)] [Reverso]     │
│                                             │
│ Популярные переводы 🇷🇺 ▾        Отчёт ⚐    │
│ ┌─────────────────────────────────────┐ [+] │
│ │ каждый раз            ← user-saved  │     │
│ ├─────────────────────────────────────┤ [+] │
│ │ всё более                       ✦AI │     │
│ ├─────────────────────────────────────┤ [+] │
│ │ все больше, каждый раз          📘  │     │
│ ├─────────────────────────────────────┤ [+] │
│ │ each time adv (on every occasion) 📘│     │
│ └─────────────────────────────────────┘     │
│                                             │
│ Примеры                                     │
│ • "...observar o que acontece abaixo."      │
│ • "Eles tomam suco de abacaxi."             │
│                                             │
│ Заметки                                     │
│ ┌────────────────────────────────────────┐  │
│ │ свободный текст…                        │ │
│ └────────────────────────────────────────┘  │
│                                             │
│              ▽  collapse                    │
├─────────────────────────────────────────────┤
│ [🗑]  [0] [1] [2] [3] [4] [5]  [✓]          │
└─────────────────────────────────────────────┘
```

## 5. Header

- 🔊 — TTS произношение слова (**post-MVP**, в MVP скрыто или disabled с tooltip).
- **Surface text** (`token_text` / `phrase_text`). Крупно. Для phrase — multi-word.
- **Тег+** chip-add (см. §9).
- **✕** — закрыть карточку.

## 6. Сохранённый перевод

- Input field с placeholder «Введите новый перевод здесь».
- Флажок справа — `target_language_code` (берётся из `user_settings.preferred_translation_language_code`, кликабелен — popover для смены target language только для текущей карточки).
- При вводе и blur'е: сохранение как `personal_translations` с `is_primary=true`, `source_type=user`. Старый primary становится non-primary, но не удаляется (история).
- Если уже есть primary — поле сразу заполнено им.

## 7. Словари (block links to external dictionaries)

- В MVP: один внутренний source — **Wiktionary** (ADR-0004) — рендерится в блок «Популярные переводы» как `📘 dictionary`.
- Дополнительно — **внешние ссылки**: chip-кнопки, открывающие popup на внешний словарь (Glosbe, Reverso, Linguee, Google Translate). Источники конфигурируются в `user_settings.external_dictionary_urls` (массив `{name, url_template}` с placeholder `{word}` и `{lang}`).
- Кнопка **«Настроить»** → переход на `/settings/dictionaries`.
- В MVP допустимо иметь дефолтный набор внешних ссылок, но без UI настройки (open question).

> **Решение по MVP-минимуму:** внутренний Wiktionary lookup обязателен. Внешние ссылки — допустимо отложить до Phase 2.

## 8. Популярные переводы

Объединённый список вариантов из всех источников, отсортированных по приоритету:

| Источник | Метка | Приоритет |
|---|---|---|
| Пользовательские (saved) | без метки, на топе | 1 |
| AI-перевод (контекстный) | `✦ AI` | 2 (если статус = `new`) |
| Wiktionary translations | `📘` | 3 |
| Wiktionary glosses (на other language) | `📘` (вторичный sense) | 4 |

- Каждая строка — кликабельная, `[+]` справа сохраняет вариант как primary `personal_translations` (создаёт новый row или promot'ит существующий).
- Click на текст без `+` — копирует в clipboard (UX hint).
- AI-метка обязательна по decision log §5: «все AI-ответы должны быть явно помечены как AI-generated».

**Поведение по статусу слова:**
- `new`: AI suggestion **первой строкой** (см. ADR-0005 §«Поведение при клике»).
- `tracked`: пользовательский primary первой строкой, остальное ниже.
- `known`: AI + словарный показаны (для подсказки), порядок без приоритета AI.
- `ignored`: блок suggestions свёрнут / скрыт; показано только «Ignored» + кнопка Reactivate (см. §11).

«Отчёт» (флажок) — кнопка отправить feedback по плохому AI-переводу. **Post-MVP**, в MVP скрыто.

## 9. Теги

- Под header'ом chip-input «Тег+» с автодополнением по существующим `item_tags` пользователя.
- Enter — добавить тег. Click на существующий tag chip — удалить.
- Tags хранятся в `item_tags` (см. domain model §8.7).

## 10. Заметки

- Свободное textarea внизу карточки.
- Сохраняется в `personal_notes.note_text` на blur (debounced).
- Markdown? — в MVP plain text. Open question.

## 11. Status / Confidence picker (footer)

```
[🗑]  [1] [2] [3] [4]  [✓]
```

Тот же виджет, что в `/vocabulary` (см. `vocabulary.md` §8). Поведение одинаковое.

> Модель хранения confidence — `0..5` (ADR-0005), но UI-пикер в MVP экспонирует только `1..4`: `5` — территория SRS-graduation (следующий успех промотирует в `known`), `0` — floor SRS-понижений, вручную не выставляется.

**Автосоздание item:** первое неявное действие на `new` слове/фразе (сохранение перевода, клик `+` на подсказке, заметка, тег) автоматически создаёт `tracked` item с `confidence 1` (ADR-0005 §«Переходы»: `new → tracked` стартует с `1`) — слово сразу подсвечивается жёлтым в тексте.

**По текущему статусу:**

| Статус | Активный элемент | Доступные действия |
|---|---|---|
| `new` | ничего (предлагается выбор) | клик `1..4` → `tracked`; клик `✓` → `known`; клик `🗑` → `ignored` |
| `tracked` (`confidence=N`) | пилюля `N` подсвечена | клик другого числа → меняет confidence; `✓` → `known`; `🗑` → `ignored` |
| `known` | `✓` подсвечен | клик `1..4` → revert в `tracked`; `🗑` → `ignored` |
| `ignored` | `🗑` подсвечен | клик `1..4` или `✓` → reactivate; вместо suggestions блок показывает «Ignored. Reactivate?» |

> **Решение:** `🗑` в карточке = установить статус `ignored`, **не** hard-delete. Hard-delete доступен только из `/vocabulary` через bulk action (см. `vocabulary.md` §6.3).

## 12. Состояния

### 12.1 Loading
Skeleton всей карточки. Header показан сразу (token_text известен), остальное — pulsing blocks.

### 12.2 AI отключён (kill-switch или нет провайдера)
- Для `new` карточки: вместо AI-suggestion первой строкой — info note «AI отключён администратором» или «AI не настроен» (без блокирующего error).
- Wiktionary suggestions показываются как обычно.

### 12.3 AI ошибка / timeout
- Inline error в блоке suggestions: «Не удалось получить AI-перевод» + retry button.
- Остальная карточка работает.

### 12.4 Wiktionary entry отсутствует
- Скрываем `📘`-suggestions без error. Если и AI выключен — показываем only user input field + «Введите перевод вручную».

### 12.5 Network error при сохранении
- Toast + автоматический retry (TanStack Query mutation retry).

## 13. Hotkeys (когда карточка открыта)

См. `reader.md` §10. Краткая таблица:
- `1..4` → set confidence
- `k` → known
- `i` → ignored
- `Esc` → close
- `Tab` → переход между элементами (a11y)
- `Enter` (в input) → save translation

## 14. Связь с backend

- `GET /vocabulary/lookup?lang=$lc&text=$normalized` — карточка по статусу, переводам, заметкам, тегам, AI cache hit. Нужно для `new` (нет item) и для `tracked` (есть item).
- `POST /vocabulary/items` — создать `token_item` или `phrase_item` (когда `new → tracked/known/ignored`).
- `PATCH /vocabulary/items/$kind/$id` — изменить статус, confidence.
- `POST /vocabulary/items/$kind/$id/translations` — добавить/promote перевод.
- `PUT /vocabulary/items/$kind/$id/notes` — обновить заметку.
- `POST /vocabulary/items/$kind/$id/tags` / `DELETE /...tags/$tag` — теги.
- `POST /ai/translate` — контекстный AI-перевод (вызывается lazy для `new` карточки): вход — `lesson_id`, `segment_id`, `surface_text`, `target_language_code`. Включает per-user AI cache (см. ADR-0003).

## 15. Open questions

- **Внешние словари в MVP:** дефолтный набор / UI конфигурации / без них вообще.
- **Markdown в notes:** plain vs markdown.
- **Phrase создание из карточки:** возможность преобразовать token-карточку в phrase, добавив соседний токен — UX отдельно.
- **Multiple primary translations** на разные target languages: в MVP `is_primary` per `(item, target_language)` — поддерживаем (domain model §8.5), UI пока показывает один target.
- **Inline play TTS** — post-MVP.
- **«Сохранённый перевод» collapsible header** vs всегда expanded.
- **Sense disambiguation:** Wiktionary возвращает несколько senses — показывать все плоско или группировать.

## 16. Не входит в MVP

- TTS (произношение слова).
- AI-объяснение грамматики, сравнение слов, генерация примеров, chat по уроку (decision log §5: только контекстный перевод выделения).
- Phrase mining suggestions.
- Auto-tagging.
- Voice input для перевода.
- Markdown в заметках.
- Reporting bad AI translations (флажок «Отчёт»).