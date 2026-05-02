# UI spec — `/register`

- Статус: Draft v1
- Дата: 2026-05-01
- Макет-референс: `docs/ui/register.png`
- Связано с: `docs/specs/2026-04-11-mvp-product-alignment-design.md` §10.3, ADR-0006, `docs/architecture/2026-04-11-mvp-domain-model.md` §5

## 1. Назначение

Регистрация нового аккаунта. После успеха — редирект на `/onboarding`.

## 2. Маршрут и доступ

- Путь: `/register`
- Доступ: гость. Авторизованный — редирект на `/library`.
- Если `FLINQ_ALLOW_PUBLIC_REGISTRATION=false` — страница рендерит «Регистрация закрыта администратором» и линк на `/login`.

## 3. Layout

```
       Регистрация

  ┌────────────────────────┐
  │ Имя                    │
  └────────────────────────┘
  ┌────────────────────────┐
  │ Электронная почта      │
  └────────────────────────┘
  ┌────────────────────────┐
  │ Пароль              👁  │
  └────────────────────────┘
  · мин 10 символов

       ┌──────────────────┐
       │  Создать аккаунт │
       └──────────────────┘

  Уже есть аккаунт? Войти
```

## 4. Поля

| Поле | Required | Валидация | DB target |
|---|---|---|---|
| Имя | да | 1..80 символов | `user_profiles.display_name` |
| Электронная почта | да | RFC-5322, unique по `users.email` | `users.email` |
| Пароль | да | min 10 символов, без правил сложности (NIST 2024) | `users.password_hash` (argon2id) |

Live-валидация на blur. Email uniqueness проверяется только при submit (не делаем `GET /auth/check-email` чтобы избежать enumeration).

> **Deviation от макета:**
> - В `register.png` показаны поля «Я хочу изучать», «Мой уровень», «Имя пользователя». В Flinq:
>   - язык изучения и UI язык собираются на отдельном `/onboarding` (см. `docs/ui/onboarding.md`);
>   - «Уровень» вырезан из MVP вместе со slider'ом библиотеки;
>   - username нет — `users.email` единственный identifier.

## 5. Первый admin

При первой регистрации с email = `FLINQ_INITIAL_ADMIN_EMAIL` (env var инсталляции) пользователь получает `users.role = admin` автоматически. Для остальных — `role = learner`. UI отличий нет.

## 6. Действия

- **Submit:** `POST /auth/register` с `{ display_name, email, password }`.
- При успехе:
  1. Backend создаёт `users`, `user_profiles` (минимум), `user_sessions`.
  2. Set-cookie сессия (auto-login).
  3. Redirect на `/onboarding`.
- Линк «Войти» → `/login`.

## 7. Состояния

| State | UI |
|---|---|
| idle | форма enabled |
| submitting | кнопка disabled + spinner |
| email taken | inline error под полем email: «Этот email уже используется» |
| password too short | inline под полем password: «Минимум 10 символов» |
| registration disabled | вместо формы — info-блок (см. §2) |
| rate-limited | «Слишком много попыток. Попробуйте через {minutes} мин» |
| server error | toast + retry |
| success | redirect `/onboarding` |

## 8. Безопасность

- **Rate limiting:** 10 регистраций / час с одного IP.
- **CSRF:** double-submit cookie.
- **Password hash:** argon2id.
- **No CAPTCHA** в MVP — рассчитываем на closed/small инсталляции; если будет abuse — Phase 2.

## 9. Связь с backend

- `POST /auth/register` — `{ display_name, email, password }` → создаёт `users`, `user_profiles` (заглушка), `user_sessions`, set-cookie.
- Endpoint возвращает 403 если registrations выключены.
- Backend module: `Identity and Settings`.

## 10. Не входит в MVP

- Email confirmation step.
- Invite-by-link flow.
- Username field.
- CAPTCHA.
- Соглашение с условиями (ToS) / privacy checkbox — добавится при необходимости в Phase 2.
- Promo блоки / preview features.