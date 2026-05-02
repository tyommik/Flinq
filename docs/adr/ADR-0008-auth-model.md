# ADR-0008 — Authentication model for MVP

- Статус: Accepted
- Дата: 2026-05-01
- Связан со: `docs/specs/2026-04-11-mvp-product-alignment-design.md` §10.3, ADR-0006 (tech stack: argon2-cffi, sessions), `docs/architecture/2026-04-11-mvp-architecture-overview.md` §12, §14, `docs/ui/login.md`, `docs/ui/register.md`, `docs/ui/onboarding.md`

## Контекст

Decision log §10.3 зафиксировал «email + password, без SSO», но оставил открытыми детали: формат сессий, password policy, политику регистрации, forgot password flow, rate limiting, bootstrap первого админа. Без этих решений нельзя начать identity module.

Целевой класс инсталляции — personal homelab + small team. Это означает: SMTP может отсутствовать, администратор — это сам пользователь или коллега, abuse-сценарии минимальны. Стандартные SaaS-механизмы (email-verification, magic-link, captcha) добавляют surface без пропорциональной выгоды.

## Решение

### Идентификатор

Единственный identifier — `users.email`. Username **не вводится** (отличие от макета `register.png`). Login принимает email, регистрация требует email. Уникальность по `users.email` (case-insensitive: всё хранится lowercase, нормализация перед `WHERE email = ...`).

### Password

- **Hash:** argon2id через `argon2-cffi` (ADR-0006). Параметры — defaults библиотеки на момент имплементации.
- **Min length:** 10 символов. Без правил сложности (NIST SP 800-63B 2024).
- **Max length:** 128 символов (защита от DoS на argon2).
- **Сравнение:** constant-time через `verify`.

### Сессии

- **Storage:** Postgres, таблица `user_sessions` (см. domain model §5.5).
- **Token:** secure random 256-bit, base64url, set-cookie `flinq_session` (HttpOnly, Secure, SameSite=Lax).
- **TTL:** 30 дней sliding — каждый запрос обновляет `last_seen_at` и продлевает `expires_at` (debounced до раз в 5 минут).
- **«Remember me» checkbox** на login:
  - Checked (default) — cookie persistent, `Max-Age=2592000`.
  - Unchecked — session cookie без `Max-Age` (живёт до закрытия браузера). Серверная запись TTL — те же 30 дней.
- **Logout:** invalidate session row (`expires_at = NOW()` или DELETE) + clear cookie.
- **Cleanup:** background job в worker'е раз в сутки удаляет `expires_at < NOW()`.

### CSRF

Double-submit cookie pattern:

- На каждый mutating запрос (`POST/PUT/PATCH/DELETE`) middleware требует header `X-CSRF-Token`.
- Cookie `flinq_csrf` (не HttpOnly, чтобы JS мог прочитать) выдаётся при создании сессии.
- Сравнение header == cookie. Mismatch — 403.
- Для GET endpoints CSRF не требуется.

### Rate limiting

- **Login:** 5 неудачных попыток за 15 минут на ключ `(client_ip, email)`. Реализуется в Redis через atomic counter с TTL.
- **Register:** 10 регистраций за час на `client_ip`.
- **Превышение:** HTTP 429 + `Retry-After` header.
- Успешный login сбрасывает counter для этого ключа.

### Anti-enumeration

- Login возвращает одинаковую ошибку «Неверный email или пароль» как для несуществующего email, так и для неверного пароля.
- Register возвращает специфичную ошибку «Этот email уже используется» — это сознательный compromise: enum через register лимитируется rate limit, и UX дороже без явного фидбека.

### Forgot password

- В MVP **нет UI**. Сброс делается админом через CLI:
  ```
  flinq reset-password user@example.com
  ```
- Команда генерирует временный пароль (16 символов), хеширует, обновляет `users.password_hash`, печатает временный пароль в stdout (админ передаёт пользователю out-of-band).
- Email-based reset link — Phase 2, требует SMTP.

### Регистрация

- **Public registration toggle:** env `FLINQ_ALLOW_PUBLIC_REGISTRATION=true|false`, default `true`.
  - При `false` страница `/register` показывает «Регистрация закрыта администратором», endpoint `POST /auth/register` возвращает 403.
- **Поля формы:** `display_name`, `email`, `password`. Языки и UI language собираются на отдельном `/onboarding` (см. `docs/ui/onboarding.md`).
- **Auto-login после register:** да, set-cookie сразу после создания записи.
- **Email verification:** **off в MVP.** Аккаунт активен сразу после register. Phase 2 — опциональный verification flow.

### Первый админ

- Env `FLINQ_INITIAL_ADMIN_EMAIL` указывает email, который при первой регистрации с этим адресом получает `users.role = admin`. Все остальные — `learner`.
- Если env не задан — первый админ создаётся вручную через CLI: `flinq create-admin user@example.com`.
- Multiple admins возможны, но создаются только админом через `flinq promote user@example.com` (post-MVP — admin UI).

### Удаление аккаунта

- Hard-delete: записи пользователя удаляются из БД (см. decision log §10.3).
- Триггер UI: `/settings/data` → «Удалить аккаунт» → confirm dialog с повторным вводом пароля.
- Endpoint: `DELETE /me` с `{ password }` в body.
- Cascade удаляет: `user_profiles`, `user_settings`, `user_sessions`, `user_learning_languages`, `token_items`, `phrase_items`, `personal_translations`, `personal_notes`, `item_tags`, `review_items`, `review_events`, `lessons` (с `owner_user_id`), `lesson_*`, `reader_positions`, `bulk_actions`, `ai_requests`, `daily_user_stats`, `lesson_progress`, `stats_snapshots`.
- **Не удаляется:** dictionary data, shared lessons других пользователей, audit log системных событий (если появится).

### Endpoints

- `POST /auth/register` — `{ display_name, email, password }` → set-cookie + redirect клиента на `/onboarding`.
- `POST /auth/login` — `{ email, password, remember_me }` → set-cookie.
- `POST /auth/logout` — invalidate session.
- `GET /me` — текущий пользователь + `needs_onboarding` flag.
- `POST /me/onboarding` — заполнение `user_profiles` и `user_learning_languages`.
- `DELETE /me` — hard-delete (требует password).
- CLI: `flinq create-admin`, `flinq promote`, `flinq reset-password`.

## Последствия

**Положительные:**

- Минимальная surface для homelab: нет SMTP-зависимости, нет внешних сервисов.
- Простая операционная модель: админ всё делает через CLI и один env.
- Server-side sessions позволяют instant invalidate (logout, ban) без сложной revocation logic для JWT.
- Argon2id + min 10 chars соответствует NIST SP 800-63B 2024 без bloat'а правил сложности.

**Отрицательные (принятые):**

- Forgot password через CLI — плохой UX для not-tech-savvy пользователя, но в personal homelab администратор и пользователь часто одно лицо или близко.
- Postgres-sessions создают write-traffic при каждом продлении — лимитируется debounce'ом до раз в 5 минут.
- Email enumeration через register form возможна — принято, лимитируется rate limit + закрытием регистрации в shared installations.
- Нет 2FA — Phase 2.
- Нет браузерной session-list / device-management UI — Phase 2.

**Обратимость:**

- Email verification, forgot password email-flow, 2FA — добавляются как opt-in без слома существующих сессий.
- Переход на JWT-only auth был бы breaking change, но отвергнут (см. альтернативы).

## Альтернативы (отвергнуты)

- **JWT-only auth** (без server-side sessions). Отвергнуто: сложный revocation flow, refresh-token гимнастика, surface для bugs. Для single-tenant MVP без межсервисной сети overkill.
- **OAuth / SSO** (Google, GitHub). Отвергнуто: внешняя зависимость, breaks self-hosted сценарий, не входит в decision log §10.3. Phase 3 enterprise.
- **Magic link login** (email-based, без пароля). Отвергнуто: требует SMTP, не работает offline.
- **Email verification обязательная.** Отвергнуто: тот же SMTP-блокер. Опциональный verification — Phase 2.
- **Username + email** (как в макете register.png). Отвергнуто: domain model не имеет username, лишнее поле без выгоды для homelab. Login по email — стандартный UX.
- **Rate limiting через slowapi vs ручная Redis-логика.** Решение оставлено на этап имплементации; обе альтернативы совместимы с этим ADR.
- **Захардкоженный admin** (через `auth.json` файл вместо env + БД). Отвергнуто: пароли в файле, не масштабируется на multiple admins.
- **Captcha при register.** Отвергнуто: privacy-unfriendly, лишний внешний сервис; для closed/small инсталляций не нужно.

## Открытые вопросы

- **`session_secret`** для подписи cookies — где хранить (env vs auto-generate at first run в файл). Решается при имплементации middleware.
- **Periodic password rehash** при изменении argon2 params — стандартный приём, реализуется при первом upgrade параметров. Не блокирует MVP.
- **Fail-safe при отсутствии Redis** для rate limiting (Redis offline = auth disabled? или auth работает без лимитов?). Рекомендация: log warning, продолжить без лимитов (availability > rate limit в self-hosted).
- **Account lockout** после N неудач (отдельно от rate limit). Не в MVP.
- **Browser fingerprinting** для detection кражи cookie. Не в MVP.