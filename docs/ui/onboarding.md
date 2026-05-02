# UI spec — `/onboarding`

- Статус: Draft v1
- Дата: 2026-05-01
- Макет-референс: нет (новый экран). Поля частично заимствованы из `register.png` («Я хочу изучать», UI language).
- Связано с: `docs/specs/2026-04-11-mvp-product-alignment-design.md` §10.1 (поддерживаемые языки), `docs/architecture/2026-04-11-mvp-domain-model.md` §5.2, §5.3

## 1. Назначение

Однократный экран сразу после регистрации — собирает минимально необходимые языковые настройки. Без него reader не знает, какой target language подставить в карточку слова.

## 2. Маршрут и доступ

- Путь: `/onboarding`
- Доступ: только что зарегистрированный `learner` без заполненных `user_profiles.ui_language_code` или `user_settings.preferred_translation_language_code`.
- Если профиль уже заполнен — редирект на `/library`.
- Skip недоступен — поля обязательны (но default'ы предзаполнены, форма submit'ится за один клик).

## 3. Layout

```
       Добро пожаловать в Flinq

  Язык интерфейса
  ┌────────────────────────┐
  │ Русский            ▾   │
  └────────────────────────┘

  Я хочу изучать
  ┌────────────────────────┐
  │ ☐ English              │
  │ ☑ Português            │
  │ ☐ Русский              │
  └────────────────────────┘
  Можно выбрать несколько

  Перевод на
  ┌────────────────────────┐
  │ Русский            ▾   │
  └────────────────────────┘

       ┌──────────────────┐
       │     Готово       │
       └──────────────────┘
```

Один экран, без шагов / прогресс-бара (форма короткая).

## 4. Поля

| Поле | Тип | Default | DB target |
|---|---|---|---|
| Язык интерфейса | single-select из `{en, ru}` | определяется по `Accept-Language` header браузера, fallback `en` | `user_profiles.ui_language_code` |
| Я хочу изучать | multi-select из `{en, ru, pt}`; min 1 | пусто | `user_settings.learning_language_codes` (массив) |
| Перевод на | single-select из `{en, ru, pt}` | = язык интерфейса | `user_settings.preferred_translation_language_code` |

Список языков берётся из `languages` (lookup-table из domain model §4.1).

> **Замечание по domain model:** `user_settings.learning_language_codes` сейчас не зафиксирован как поле — есть `preferred_translation_language_code`, но нет массива изучаемых языков. Нужна правка domain model (добавить `learning_language_codes TEXT[]`) или вынести в отдельную таблицу `user_learning_languages`. См. §10.

## 5. Действия

- **Submit:** `POST /me/onboarding` с `{ ui_language, learning_languages, translation_language }`.
- При успехе → redirect `/learn/:firstLang/library`, где `:firstLang` — первый выбранный из `learning_languages`. Бэкенд при сохранении заполняет `user_settings.last_learning_language_code = :firstLang`.
- Изменить позже — через `/settings/profile` и `/settings/preferences`.

## 6. Состояния

| State | UI |
|---|---|
| idle | default'ы предзаполнены |
| submitting | кнопка disabled + spinner |
| no learning lang selected | inline error под чекбоксами: «Выберите хотя бы один язык» |
| server error | toast + retry |
| success | redirect `/learn/:firstLang/library` |

## 7. Связь с backend

- `POST /me/onboarding` — записывает в `user_profiles` и `user_settings`. Идемпотентен (повторный submit перезаписывает).
- `GET /me` после регистрации возвращает флаг `needs_onboarding: bool` — клиентский router решает, куда пустить.

## 8. Mobile

Та же форма, full-width поля, padding 16px.

## 9. Не входит в MVP

- Multi-step wizard.
- Опросник целей (минут в день, слов в неделю — поля `user_settings.daily_goal_*` есть, но UX выбора отложен).
- Импорт демо-урока / tutorial.
- Выбор уровня владения языком.

## 10. Open questions / domain model adjustments

- **`user_settings.learning_language_codes`** как массив — нужно добавить в domain model и миграции. Альтернатива — отдельная join-table `user_learning_languages(user_id, language_code)`. Рекомендация: отдельная таблица (легче расширять — позже могут потребоваться per-language preferences).
- **Onboarding completion flag** — отдельное поле `users.onboarded_at TIMESTAMP NULL` или вычислять по наличию записей в `user_settings`. Рекомендация: явное поле `onboarded_at` (clearer semantics).
- **`user_settings.last_learning_language_code`** — для `/` redirect и TopBar language picker. См. `library.md` §16.