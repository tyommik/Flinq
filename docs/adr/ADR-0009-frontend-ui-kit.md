# ADR-0009 — Frontend UI kit and design tokens

- Статус: Accepted
- Дата: 2026-05-01
- Связан со: ADR-0006 (frontend stack: React 19 + TS + Tailwind v4), ADR-0005 (reader status colors), `docs/ui/library.md`, `docs/ui/reader.md`, `docs/ui/word_card.md`

## Контекст

ADR-0006 зафиксировал tech stack, но выбор конкретной UI-библиотеки и палитра токенов были оставлены до первого реального дизайна. UI-спеки library / vocabulary / reader / word_card / login / register / onboarding готовы, разработка стартует. Без зафиксированной библиотеки и токенов компоненты будут писаться в разнобой.

## Решение

### UI kit: shadcn/ui

**shadcn/ui** поверх **Radix UI** и **Tailwind CSS v4**.

shadcn/ui — не npm-пакет, а CLI-генератор: `npx shadcn@latest add button` копирует исходник компонента в `frontend/src/components/ui/`, после чего он редактируется как обычный код.

Преимущества:
- **Owned code** — компоненты в репозитории, без зависимости от мажор-релиза библиотеки.
- **Radix primitives** — accessibility (focus-trap, ARIA, keyboard nav) сделана.
- **Tailwind v4 native** — нет runtime CSS-in-JS, сборка лёгкая.
- **TypeScript types** из коробки.

### Установка

- `npx shadcn@latest init` при старте frontend-эпика — генерирует `components.json`, базовые токены, утилиту `cn` (clsx + tailwind-merge).
- `npx shadcn@latest add button input form dialog dropdown-menu …` — по мере появления реальных потребностей. Не добавляем заранее всё подряд.
- Компоненты живут в `frontend/src/components/ui/` (per shadcn convention).
- Generic shared компоненты (`AppTopBar`, `LessonCard`, etc.) — в `frontend/src/components/`. Feature-specific — в `frontend/src/features/<feature>/`.

### Design tokens — двухуровневая модель

1. **Базовые tokens** в `:root` (`globals.css`) — значения в `oklch()`:
   - shadcn semantic: `--background`, `--foreground`, `--primary`, `--border`, `--ring`, `--radius`, и т.д.
   - app-specific: `--reader-new`, `--reader-tracked`, `--confidence-0..5`.
2. **Tailwind theme mapping** в `@theme` того же файла — bridge для Tailwind utility-классов: `--color-background: var(--background)` → `bg-background`. В Tailwind v4 `@theme` заменяет старый `tailwind.config.ts`.

### Палитра MVP

| Token | Назначение |
|---|---|
| `--background` | Page bg (white) |
| `--foreground` | Default text (near-black) |
| `--card`, `--card-foreground` | Контейнеры (lesson card, word card) |
| `--popover`, `--popover-foreground` | Поповеры, dropdown |
| `--primary`, `--primary-foreground` | Brand green (CTA: «Импортировать урок», «Создать аккаунт», «Вход») |
| `--secondary`, `--secondary-foreground` | Secondary buttons |
| `--muted`, `--muted-foreground` | Disabled, placeholders, helper text |
| `--accent`, `--accent-foreground` | Hover states, subtle highlights |
| `--destructive`, `--destructive-foreground` | Errors, delete actions |
| `--border`, `--input`, `--ring` | Линии, фокус |
| `--reader-new` | Бледно-голубой fill для `new` слов (ADR-0005) |
| `--reader-tracked` | Жёлтый fill для `tracked` слов (ADR-0005) |
| `--confidence-0..5` | Yellow gradient для confidence pills (опциональный визуальный градиент) |

**Light mode only в MVP.** Dark mode — Phase 2 (повторяет палитру под `[data-theme="dark"]` или `prefers-color-scheme`).

### Типография

- **Font family sans:** `Inter` (UI). Self-hosted в `frontend/public/fonts/`.
- **Font family serif:** не подключаем в MVP. Reader-customization (serif/sans toggle из `reader.md` §7) — Phase 2.
- **Scale:** Tailwind default'ы (`text-xs..text-4xl`).
- **Reader-specific:** `text-lg leading-loose` в `<ReaderText>` компоненте, не глобально.

### Иконки

`lucide-react` (уже в `package.json`). Default 20px, в плотных таблицах — 16px.

### Spacing, radii, shadows

- Spacing — Tailwind default (0.25rem step).
- Radii — `--radius: 0.5rem` базовый. Pill-кнопки — `rounded-full`. Карточки — `rounded-lg`.
- Shadows — Tailwind default'ы. Кастомных нет.

### Z-index layers

Не вводим numeric utility-классы напрямую. Semantic CSS-переменные:

```
--z-dropdown:       50
--z-sticky:         60
--z-fixed:          70
--z-modal-backdrop: 80
--z-modal:          90
--z-popover:       100
--z-toast:         110
```

## Последствия

**Положительные:**
- shadcn даёт 80% UI-набора без ручной работы.
- Owned code = нет breaking-change boli при upgrade.
- Tailwind v4 + oklch = перцептивно ровные градиенты (важно для confidence scale).
- Один source of truth для tokens (`globals.css`), без `tailwind.config.ts`.

**Отрицательные (принятые):**
- Каждый shadcn-компонент — несколько сотен строк в репо. Размер растёт. Принято: контроль > размер.
- Update shadcn — ручной (`npx shadcn diff`, mergeкод). Раз в полгода — приемлемо.
- Radix peer deps приходят с shadcn — нужно следить за их upgrade-циклом.

## Альтернативы (отвергнуты)

- **Radix UI напрямую** без shadcn — пришлось бы писать стили с нуля.
- **Park UI / Ark UI** — младше, меньше community-примеров.
- **Mantine v8** — runtime CSS-in-JS, дублирует Tailwind.
- **Chakra UI v3** — собственный стилевой движок, конфликт с Tailwind.
- **MUI Joy / Material** — heavy bundle, чужой дизайн-язык.
- **Headless UI (Tailwind Labs)** — меньше компонентов, нет popover/combobox.
- **С нуля custom** — 2–3 месяца на полноценный a11y, не оправдано для MVP.

## Открытые вопросы

- **Шрифт:** Inter — boring choice; можно заменить на system-ui для меньшего веса.
- **Confidence gradient в reader:** в MVP равномерный `--reader-tracked`, использование `--confidence-0..5` опционально по ADR-0005.
- **Toast library:** `sonner` (рекомендован shadcn) или встроенный `<Toast>`. Решим при первой реальной потребности.
- **Theme provider:** для будущего dark mode — собственный или `next-themes`-equivalent.