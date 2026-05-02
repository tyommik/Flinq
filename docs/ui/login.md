# UI spec — `/login`

- Статус: Draft v1
- Дата: 2026-05-01
- Макет-референс: `docs/ui/login.png`
- Связано с: `docs/specs/2026-04-11-mvp-product-alignment-design.md` §10.3, ADR-0006, `docs/architecture/2026-04-11-mvp-domain-model.md` §5.1

## 1. Назначение

Вход в систему по email + password. Единственный auth-метод в MVP.

## 2. Маршрут и доступ

- Путь: `/login`
- Доступ: гость. Авторизованный пользователь редиректится на `/library`.

## 3. Layout

```
        Вход

  ┌────────────────────────┐
  │ Электронная почта      │
  └────────────────────────┘
  ┌────────────────────────┐
  │ Пароль              👁  │
  └────────────────────────┘

  ☑ Запомнить меня

       ┌──────────┐
       │   Вход   │
       └──────────┘

  Нет аккаунта? Зарегистрироваться
```

Центрированная форма ~400px шириной на белой/серой странице. Без TopBar (auth-страницы — public layout).

## 4. Поля

| Поле | Required | Валидация |
|---|---|---|
| Email | да | RFC-5322, lowercase нормализация перед отправкой |
| Password | да | non-empty |
| Запомнить меня (checkbox) | — | по default `true`. См. §6 |

> **Deviation от макета:** в `login.png` поле названо «Имя пользователя или электронная почта». В Flinq username отсутствует в domain model (`users.email` — единственный identifier). Меняем label на «Электронная почта».

## 5. Действия

- **Submit:** `POST /auth/login` с `{ email, password, remember_me }`.
- **Кнопка показать/скрыть пароль** — иконка глаза в input'е.
- **Линк «Зарегистрироваться»** → `/register`.
- **Нет линка «Забыли пароль?»** в MVP — сброс делается админом через CLI (`flinq reset-password user@x.com`). Inline note в empty state error: «Забыли пароль? Обратитесь к администратору» — без отдельной страницы.

## 6. Запомнить меня

- Checked (default) — set-cookie с `Max-Age=30 days`, sliding (обновляется на каждом запросе).
- Unchecked — session cookie без `Max-Age` (живёт до закрытия браузера).
- Серверная сессия в `user_sessions` создаётся в обоих случаях; разница только в TTL cookie на клиенте.

## 7. Состояния

| State | UI |
|---|---|
| idle | форма enabled |
| submitting | кнопка disabled + spinner, поля disabled |
| invalid creds | inline error под формой: «Неверный email или пароль» (без указания, что именно не так — anti-enumeration) |
| rate-limited | inline error: «Слишком много попыток. Попробуйте через {minutes} мин» |
| server error | toast «Не удалось войти. Попробуйте позже» + retry |
| success | redirect на `/library` (или на `?next=` параметр) |

## 8. Безопасность

- **Rate limiting:** 5 неудачных попыток / 15 мин на (IP + email). Реализуется в backend через Redis. После лимита — 429.
- **CSRF:** double-submit cookie. Login endpoint принимает CSRF token из header.
- **Anti-enumeration:** одинаковая ошибка для «email не найден» и «пароль неверный».
- **Password hash:** argon2id (ADR-0006).

## 9. Hotkeys

- `Enter` в любом поле — submit.
- `Tab` — навигация между полями.

## 10. Mobile

Та же форма, padding-x 16px, поля full-width.

## 11. Связь с backend

- `POST /auth/login` — `{ email, password, remember_me }` → set session cookie + CSRF token.
- `POST /auth/logout` — invalidates session.
- Backend module: `Identity and Settings` (architecture overview §7.1).

## 12. Не входит в MVP

- SSO / OAuth providers.
- Magic link login.
- 2FA.
- Forgot password UI и email-flow.
- Captcha.
- Social proof / promo блоки на форме.