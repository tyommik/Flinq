# Reader Per-Sentence Design Rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Привести sentence-режим страницы урока к Figma-макету «Reader (per sentence) — Desktop 1440» (спека: `docs/superpowers/specs/2026-07-12-reader-sentence-design-design.md`).

**Architecture:** Переработка существующих компонентов фичи `frontend/src/features/reader` на месте: SubToolbar без названия урока с центрированным прогрессом, левовыровненный текст 20px/36px с новыми цветами подсветок, новый компонент `SentenceVocabList` (строки с переводами через `vocabularyApi.lookup`), нижняя панель с тремя действиями, стрелки навигации по краям экрана в `ReaderPage`. Логика (хоткеи, позиция, undo, запросы) не меняется.

**Tech Stack:** React 19, TypeScript, Tailwind v4, TanStack Query v5, vitest + @testing-library/react, lucide-react.

## Global Constraints

- Все команды выполнять из `frontend/`: тесты `npm test -- --run <файл>`, линт `npm run lint`, сборка `npm run build`.
- Page-режим (`PageView.tsx`) не трогать.
- Аудио-элементы — disabled-заглушки с `title="Скоро"`.
- Не добавлять Co-Authored-By в коммиты. Коммитить только явно перечисленные пути (`git commit -- <paths>`), в индексе лежит посторонний staged `backend/uv.lock`.
- Цвета макета: tracked-подсветка `#ffeba8`, new-подсветка `#c6dfff`, кружок tracked `#ffdb8c`, текст в кружке `#523812`, бордер Play `#D9DBE0`.

---

### Task 1: Цвета подсветок и форма выделения токенов

**Files:**
- Modify: `frontend/src/styles/globals.css:51-53` (значения `--reader-new-bg` / `--reader-tracked-bg`, новые токены кружков)
- Modify: `frontend/src/features/reader/TokenSpan.tsx`
- Test: `frontend/src/features/reader/TokenSpan.test.tsx` (существующий — проверить, что проходит)

**Interfaces:**
- Consumes: ничего нового.
- Produces: CSS-токены `--reader-status-tracked-bg: #ffdb8c` и `--reader-status-foreground: #523812` (используются в Task 4). Подсветки `--reader-new-bg: #c6dfff`, `--reader-tracked-bg: #ffeba8`.

- [ ] **Step 1: Обновить токены в `globals.css`**

Заменить блок:

```css
  /* Reader token highlight backgrounds (FLQ-4.9) */
  --reader-new-bg: #e0f2fe;
  --reader-tracked-bg: #fef08a;
```

на:

```css
  /* Reader token highlight backgrounds (FLQ-4.9) */
  --reader-new-bg: #c6dfff;
  --reader-tracked-bg: #ffeba8;

  /* Reader sentence-vocab status circles */
  --reader-status-tracked-bg: #ffdb8c;
  --reader-status-foreground: #523812;
```

- [ ] **Step 2: Обновить `TokenSpan.tsx` — скругление 4px и паддинг только у подсвеченных слов**

Сейчас все словесные токены получают `rounded-sm px-px`. По макету подсветка — скругление 4px и паддинг 4px по бокам; слова без подсветки (known/ignored) паддинга не получают. Заменить вычисление `bg` и `className`:

```tsx
  const s = status?.s
  const active = s === 'tracked' && (status?.c ?? 0) >= 1
  const highlight = active
    ? 'rounded bg-[var(--reader-tracked-bg)] px-1'
    : s === 'known' || s === 'ignored'
      ? ''
      : 'rounded bg-[var(--reader-new-bg)] px-1'
  return (
    <span
      data-ordinal={token.i}
      role="button"
      tabIndex={-1}
      className={`cursor-pointer hover:brightness-95 ${highlight}`}
      onClick={() => onWordClick?.(token)}
    >
      {token.t}
    </span>
  )
```

- [ ] **Step 3: Прогнать тесты TokenSpan**

Run: `cd frontend && npm test -- --run src/features/reader/TokenSpan.test.tsx`
Expected: PASS (тесты проверяют только наличие/отсутствие `bg-[var(--reader-new-bg)]`/`bg-[var(--reader-tracked-bg)]` в className — имена не менялись).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles/globals.css frontend/src/features/reader/TokenSpan.tsx
git commit -m "style(reader): mockup highlight colors and 4px rounded token highlights" -- frontend/src/styles/globals.css frontend/src/features/reader/TokenSpan.tsx
```

---

### Task 2: SubToolbar — прогресс по центру, без названия урока

**Files:**
- Modify: `frontend/src/features/reader/ReaderTopBar.tsx`
- Modify: `frontend/src/features/reader/ReaderPage.tsx:322-330` (убрать `title` из пропсов)
- Test: `frontend/src/features/reader/ReaderPage.test.tsx` (существующий — проверить, что проходит)

**Interfaces:**
- Consumes: ничего нового.
- Produces: `ReaderTopBar` Props теперь `{ lang: string; progressPercent: number; mode: ViewMode; sidebarOpen: boolean; onToggleSidebar: () => void }` — без `title`. Task 6 (ReaderPage) полагается на эту сигнатуру.

- [ ] **Step 1: Переписать разметку `ReaderTopBar`**

Убрать `title` из `Props` и деструктуризации. Заменить весь возвращаемый JSX (импорты и дропдаун «Aa» с `SIZE_OPTIONS`/`LINE_HEIGHT_OPTIONS` не меняются):

```tsx
  return (
    <div className="flex h-14 items-center gap-4 border-b border-border">
      <button
        type="button"
        aria-label="Закрыть"
        onClick={() => {
          void navigate({ to: '/learn/$lang/library', params: { lang } })
        }}
        className="rounded-md p-2 hover:bg-accent"
      >
        <X className="h-5 w-5" />
      </button>

      <div className="relative mx-auto h-1 w-full max-w-[700px] flex-1 rounded-full bg-muted">
        <div
          className="h-1 rounded-full bg-primary"
          style={{ width: `${progressPercent}%` }}
        />
        <div
          className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary"
          style={{ left: `${progressPercent}%` }}
        />
      </div>

      <DropdownMenu>
        {/* без изменений */}
      </DropdownMenu>

      {mode === 'page' && (
        <button
          type="button"
          aria-label="Оглавление"
          aria-pressed={sidebarOpen}
          onClick={onToggleSidebar}
          className="rounded-md p-2 hover:bg-accent"
        >
          <PanelLeft className="h-5 w-5" />
        </button>
      )}
    </div>
  )
```

- [ ] **Step 2: Убрать `title` в `ReaderPage.tsx`**

```tsx
      <ReaderTopBar
        lang={lang}
        progressPercent={progressPercent}
        mode={mode}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={toggleSidebar}
      />
```

- [ ] **Step 3: Прогнать тесты ReaderPage и typecheck**

Run: `cd frontend && npm test -- --run src/features/reader/ReaderPage.test.tsx && npx tsc -b --noEmit`
Expected: PASS (тесты не проверяют название урока в тулбаре).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/reader/ReaderTopBar.tsx frontend/src/features/reader/ReaderPage.tsx
git commit -m "feat(reader): centered progress subtoolbar per mockup" -- frontend/src/features/reader/ReaderTopBar.tsx frontend/src/features/reader/ReaderPage.tsx
```

---

### Task 3: Нижняя панель — три действия

**Files:**
- Modify: `frontend/src/features/reader/BottomToolbar.tsx` (полная замена)
- Test: `frontend/src/features/reader/ReaderPage.test.tsx` (существующий — проверить, что проходит)

**Interfaces:**
- Consumes: `ViewMode` из `./readerStore`.
- Produces: сигнатура `BottomToolbar` не меняется: `{ mode: ViewMode; onToggleMode: () => void }`.

- [ ] **Step 1: Заменить содержимое `BottomToolbar.tsx` целиком**

```tsx
import type { ViewMode } from './readerStore'

interface Props {
  mode: ViewMode
  onToggleMode: () => void
}

interface ActionProps {
  icon: string
  label: string
  onClick?: () => void
  disabled?: boolean
  title?: string
}

function Action({ icon, label, onClick, disabled, title }: ActionProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="flex h-14 flex-col items-center justify-center gap-1 rounded-md text-sm hover:bg-accent disabled:pointer-events-none disabled:opacity-50"
    >
      <span aria-hidden className="text-lg leading-none">
        {icon}
      </span>
      <span>{label}</span>
    </button>
  )
}

export function BottomToolbar({ mode, onToggleMode }: Props) {
  return (
    <div className="grid grid-cols-3 border-t border-border py-3">
      <Action icon="♪" label="Сгенерировать аудио" disabled title="Скоро" />
      <Action
        icon="📖"
        label={mode === 'sentence' ? 'Показать всю страницу' : 'По предложениям'}
        onClick={onToggleMode}
      />
      <Action icon="✓" label="Повторить лексику" disabled title="Скоро (FLQ-7)" />
    </div>
  )
}
```

- [ ] **Step 2: Прогнать тесты ReaderPage**

Run: `cd frontend && npm test -- --run src/features/reader/ReaderPage.test.tsx`
Expected: PASS (строки «Показать весь текст»/«Повторение» в тестах не используются — проверено grep'ом).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/reader/BottomToolbar.tsx
git commit -m "feat(reader): bottom toolbar with three icon-over-label actions" -- frontend/src/features/reader/BottomToolbar.tsx
```

---

### Task 4: Компонент SentenceVocabList

**Files:**
- Create: `frontend/src/features/reader/SentenceVocabList.tsx`
- Test (create): `frontend/src/features/reader/SentenceVocabList.test.tsx`

**Interfaces:**
- Consumes: `wordLookupKey(lang, text, target)` из `./useWordCard` (тот же query key, что у WordCard — общий кэш; WordCard делает lookup по `word.n`), `vocabularyApi.lookup(lang, text, target): Promise<WordLookup>` из `@/api/vocabulary`, типы `StatusMap`, `WordToken` из `@/api/reader`, токены `--reader-status-tracked-bg`, `--reader-status-foreground`, `--reader-new-bg` из Task 1.
- Produces: `export function SentenceVocabList(props: { words: WordToken[]; statuses: StatusMap; lang: string; target: string; onWordClick?: (word: WordToken) => void }): JSX.Element | null`. Рендерит `<ul data-testid="sentence-vocab">`; при `words.length === 0` возвращает `null`. Task 5 использует ровно эту сигнатуру.

- [ ] **Step 1: Написать падающий тест `SentenceVocabList.test.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { StatusMap, WordToken } from '@/api/reader'
import type { WordLookup } from '@/api/vocabulary'

vi.mock('@/api/vocabulary', () => ({
  vocabularyApi: { lookup: vi.fn() },
}))

import { vocabularyApi } from '@/api/vocabulary'

import { SentenceVocabList } from './SentenceVocabList'

const words: WordToken[] = [
  { t: 'Hello', n: 'hello', i: 0 },
  { t: 'world', n: 'world', i: 2 },
]

const statuses: StatusMap = {
  hello: { s: 'tracked', c: 2 },
  // 'world' — без статуса (new)
}

const emptyLookup: WordLookup = {
  item_id: null,
  status: 'new',
  confidence: null,
  translations: { primary: null, all: [] },
  note: null,
  tags: [],
}

function renderList(overrides: Partial<Parameters<typeof SentenceVocabList>[0]> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onWordClick = vi.fn()
  render(
    <QueryClientProvider client={queryClient}>
      <SentenceVocabList
        words={words}
        statuses={statuses}
        lang="en"
        target="ru"
        onWordClick={onWordClick}
        {...overrides}
      />
    </QueryClientProvider>,
  )
  return { onWordClick }
}

describe('SentenceVocabList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(vocabularyApi.lookup).mockResolvedValue(emptyLookup)
  })

  it('renders a confidence number for tracked words and a dot for new words', () => {
    renderList()

    const vocab = screen.getByTestId('sentence-vocab')
    expect(within(vocab).getByText('2')).toBeInTheDocument()
    expect(within(vocab).getByText('•')).toBeInTheDocument()
    expect(within(vocab).getByText('Hello')).toBeInTheDocument()
    expect(within(vocab).getByText('world')).toBeInTheDocument()
  })

  it('shows the primary translation from the vocabulary lookup under the word', async () => {
    vi.mocked(vocabularyApi.lookup).mockImplementation((_lang, text) =>
      Promise.resolve({
        ...emptyLookup,
        translations: {
          primary: {
            id: 't1',
            text: text === 'hello' ? 'привет' : 'мир',
            target_language_code: 'ru',
            is_primary: true,
            source_type: 'user',
          },
          all: [],
        },
      }),
    )

    renderList()

    expect(await screen.findByText('привет')).toBeInTheDocument()
    expect(await screen.findByText('мир')).toBeInTheDocument()
  })

  it('renders no translation line when the lookup has no primary translation', async () => {
    renderList()

    await vi.waitFor(() => expect(vocabularyApi.lookup).toHaveBeenCalledTimes(2))
    expect(screen.getByTestId('sentence-vocab').querySelectorAll('li').length).toBe(2)
  })

  it('calls onWordClick with the token when a row is clicked', () => {
    const { onWordClick } = renderList()

    fireEvent.click(screen.getByText('Hello'))

    expect(onWordClick).toHaveBeenCalledWith({ t: 'Hello', n: 'hello', i: 0 })
  })

  it('renders nothing for an empty word list', () => {
    renderList({ words: [] })

    expect(screen.queryByTestId('sentence-vocab')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && npm test -- --run src/features/reader/SentenceVocabList.test.tsx`
Expected: FAIL — модуль `./SentenceVocabList` не существует.

- [ ] **Step 3: Реализовать `SentenceVocabList.tsx`**

```tsx
import { useQueries } from '@tanstack/react-query'
import { Volume2 } from 'lucide-react'

import type { StatusMap, WordToken } from '@/api/reader'
import { vocabularyApi } from '@/api/vocabulary'
import { cn } from '@/lib/utils'

import { wordLookupKey } from './useWordCard'

interface Props {
  words: WordToken[]
  statuses: StatusMap
  lang: string
  target: string
  onWordClick?: (word: WordToken) => void
}

export function SentenceVocabList({ words, statuses, lang, target, onWordClick }: Props) {
  // Тот же query key, что у WordCard (lookup по нормализованной форме) —
  // открытие карточки и список делят кэш и не дублируют запросы.
  const lookups = useQueries({
    queries: words.map((w) => ({
      queryKey: wordLookupKey(lang, w.n, target),
      queryFn: () => vocabularyApi.lookup(lang, w.n, target),
    })),
  })

  if (words.length === 0) return null

  return (
    <ul data-testid="sentence-vocab">
      {words.map((w, idx) => {
        const tracked = statuses[w.n]?.s === 'tracked'
        const translation = lookups[idx]?.data?.translations.primary?.text ?? null
        return (
          <li key={w.n}>
            <button
              type="button"
              onClick={() => onWordClick?.(w)}
              className="flex w-full items-center gap-4 rounded-md py-3 text-left hover:bg-accent/50"
            >
              <span
                className={cn(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold text-[var(--reader-status-foreground)]',
                  tracked
                    ? 'bg-[var(--reader-status-tracked-bg)]'
                    : 'bg-[var(--reader-new-bg)]',
                )}
              >
                {tracked ? (statuses[w.n]?.c ?? 0) : '•'}
              </span>
              <span className="min-w-0">
                <span className="flex items-center gap-2">
                  <span className="font-medium">{w.t}</span>
                  <Volume2
                    aria-hidden
                    className="h-3.5 w-3.5 text-muted-foreground opacity-60"
                  />
                </span>
                {translation && (
                  <span className="mt-0.5 block text-sm text-muted-foreground">
                    {translation}
                  </span>
                )}
              </span>
            </button>
            {idx < words.length - 1 && (
              <div aria-hidden className="ml-11 border-b border-border" />
            )}
          </li>
        )
      })}
    </ul>
  )
}
```

- [ ] **Step 4: Прогнать тест**

Run: `cd frontend && npm test -- --run src/features/reader/SentenceVocabList.test.tsx`
Expected: PASS (5 тестов).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/reader/SentenceVocabList.tsx frontend/src/features/reader/SentenceVocabList.test.tsx
git commit -m "feat(reader): sentence vocab list rows with lookup translations" -- frontend/src/features/reader/SentenceVocabList.tsx frontend/src/features/reader/SentenceVocabList.test.tsx
```

---

### Task 5: Переработка SentenceView

**Files:**
- Modify: `frontend/src/features/reader/SentenceView.tsx`
- Modify: `frontend/src/features/reader/SentenceView.test.tsx`

**Interfaces:**
- Consumes: `SentenceVocabList` из Task 4 (сигнатура — см. Task 4 Produces).
- Produces: новая сигнатура Props `SentenceView`: `{ lessonId: string; sentence: Sentence; statuses: StatusMap; lang: string; targetLang: 'en' | 'ru' | 'pt'; onWordClick?: (word: { t: string; n: string; i: number }) => void }` — **удалены** `onPrev/onNext/canPrev/canNext`, **добавлен** `lang` (код языка урока для lookup). `DEFAULT_TRANSLATION_LANG` экспортируется как раньше. Task 6 полагается на эту сигнатуру.

- [ ] **Step 1: Обновить тесты `SentenceView.test.tsx`**

Изменения относительно текущего файла:

1. Добавить мок vocabulary API после существующего мока `@/api/reader`:

```tsx
vi.mock('@/api/vocabulary', () => ({
  vocabularyApi: { lookup: vi.fn() },
}))
```

и импорт: `import { vocabularyApi } from '@/api/vocabulary'`.

2. В `renderView` убрать `onPrev`/`onNext`/`canPrev`/`canNext`, добавить `lang="en"`; вернуть только `{ onWordClick }`:

```tsx
function renderView(overrides: Partial<ComponentProps<typeof SentenceView>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onWordClick = vi.fn()
  render(
    <QueryClientProvider client={queryClient}>
      <SentenceView
        lessonId="lesson-1"
        sentence={sentence}
        statuses={statuses}
        lang="en"
        targetLang={DEFAULT_TRANSLATION_LANG}
        onWordClick={onWordClick}
        {...overrides}
      />
    </QueryClientProvider>,
  )
  return { onWordClick }
}
```

3. В `beforeEach` добавить дефолтный resolve для lookup:

```tsx
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null,
      status: 'new',
      confidence: null,
      translations: { primary: null, all: [] },
      note: null,
      tags: [],
    })
  })
```

4. Заменить три vocab-теста и удалить тест про prev/next-кнопки (`'disables the prev/next buttons per canPrev/canNext'` — навигация уехала в ReaderPage, Task 6):

```tsx
  it('lists tracked and new words in the vocab list, excluding known words', () => {
    renderView()

    const vocab = screen.getByTestId('sentence-vocab')
    expect(within(vocab).getByText('Hello')).toBeInTheDocument()
    expect(within(vocab).getByText('2')).toBeInTheDocument()
    expect(within(vocab).getByText('world')).toBeInTheDocument()
    expect(within(vocab).getByText('•')).toBeInTheDocument()
    expect(within(vocab).queryByText('brave')).not.toBeInTheDocument()
  })

  it('omits the vocab list entirely when the sentence has only known words', () => {
    renderView({
      sentence: {
        ...sentence,
        tokens: [{ t: 'brave', n: 'brave', i: 1 }, { p: '.' }],
      },
    })
    expect(screen.queryByTestId('sentence-vocab')).not.toBeInTheDocument()
  })

  it('calls onWordClick with the token when a vocab row is clicked', () => {
    const { onWordClick } = renderView()

    const vocab = screen.getByTestId('sentence-vocab')
    fireEvent.click(within(vocab).getByText('Hello'))

    expect(onWordClick).toHaveBeenCalledWith({ t: 'Hello', n: 'hello', i: 0 })
  })

  it('renders the disabled play-audio stub', () => {
    renderView()

    expect(screen.getByRole('button', { name: 'Воспроизвести аудио' })).toBeDisabled()
  })
```

Примечание: во втором тесте меняется `sentence`, а не `statuses`, потому что `world` без статуса — «новое» слово и попало бы в список.

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd frontend && npm test -- --run src/features/reader/SentenceView.test.tsx`
Expected: FAIL — новые пропсы/разметка ещё не реализованы (TS-ошибка на `lang` и падения vocab-тестов).

- [ ] **Step 3: Переписать `SentenceView.tsx`**

Полное новое содержимое:

```tsx
import { useState } from 'react'
import { Play } from 'lucide-react'

import { ApiError } from '@/api/client'
import { isWord, type Sentence, type StatusMap, type WordToken } from '@/api/reader'

import { SentenceVocabList } from './SentenceVocabList'
import { TokenSpan } from './TokenSpan'
import { useSegmentTranslation } from './useReaderQueries'

// TODO(FLQ-9): read from user settings
export const DEFAULT_TRANSLATION_LANG = 'ru' as const

interface SelectedWord {
  t: string
  n: string
  i: number
}

interface Props {
  lessonId: string
  sentence: Sentence
  statuses: StatusMap
  lang: string
  targetLang: 'en' | 'ru' | 'pt'
  onWordClick?: (word: SelectedWord) => void
}

function translationErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 503) {
    return 'AI отключён администратором'
  }
  return 'Не удалось перевести'
}

// Слова для списка лексики: изучаемые (tracked) и новые (без статуса).
// known/ignored не показываем. Дедупликация по нормализованной форме.
function collectVocabWords(sentence: Sentence, statuses: StatusMap): WordToken[] {
  const seen = new Set<string>()
  const words: WordToken[] = []
  for (const token of sentence.tokens) {
    if (!isWord(token)) continue
    const s = statuses[token.n]?.s
    if (s === 'known' || s === 'ignored') continue
    if (seen.has(token.n)) continue
    seen.add(token.n)
    words.push(token)
  }
  return words
}

export function SentenceView({ lessonId, sentence, statuses, lang, targetLang, onWordClick }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [translationRequested, setTranslationRequested] = useState(false)

  const translation = useSegmentTranslation(
    lessonId,
    sentence.seg_id,
    targetLang,
    translationRequested,
  )

  const handleToggle = () => {
    if (!translationRequested) setTranslationRequested(true)
    setExpanded((e) => !e)
  }

  const vocabWords = collectVocabWords(sentence, statuses)

  const showRetry =
    translation.isError && !(translation.error instanceof ApiError && translation.error.status === 503)

  return (
    <div className="mx-auto max-w-[900px]">
      <div className="flex justify-center">
        <button
          type="button"
          disabled
          title="Скоро"
          aria-label="Воспроизвести аудио"
          className="flex h-[54px] w-[54px] items-center justify-center rounded-full border-[1.5px] border-[#D9DBE0] disabled:opacity-60"
        >
          <Play aria-hidden className="h-5 w-5" />
        </button>
      </div>

      <div className="mt-10 px-4 sm:px-16">
        <p className="text-xl leading-[1.8]">
          {sentence.tokens.map((token, i) => (
            <TokenSpan
              key={i}
              token={token}
              status={isWord(token) ? statuses[token.n] : undefined}
              onWordClick={onWordClick}
            />
          ))}
        </p>

        <div className="mt-4">
          <button
            type="button"
            data-testid="toggle-translation"
            onClick={handleToggle}
            className="text-sm text-muted-foreground underline hover:text-foreground"
          >
            Показать перевод ▾
          </button>
        </div>

        {expanded && (
          <div data-testid="sentence-translation" className="mt-2 text-sm italic">
            {translation.isLoading && <p className="text-muted-foreground">Переводим…</p>}
            {translation.isError && (
              <div>
                <p className="text-destructive">{translationErrorMessage(translation.error)}</p>
                {showRetry && (
                  <button
                    type="button"
                    onClick={() => translation.refetch()}
                    className="mt-1 text-sm underline"
                  >
                    Повторить
                  </button>
                )}
              </div>
            )}
            {translation.isSuccess && (
              <p>
                {translation.data.text}
                {translation.data.source === 'ai' && (
                  <span className="ml-2 inline-block rounded-full bg-muted px-2 py-0.5 text-xs font-medium not-italic">
                    AI
                  </span>
                )}
              </p>
            )}
          </div>
        )}

        <div className="mt-8">
          <SentenceVocabList
            words={vocabWords}
            statuses={statuses}
            lang={lang}
            target={targetLang}
            onWordClick={onWordClick}
          />
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Прогнать тесты SentenceView**

Run: `cd frontend && npm test -- --run src/features/reader/SentenceView.test.tsx`
Expected: FAIL только в `ReaderPage`-цепочке? Нет: сам файл должен пройти PASS. `ReaderPage.tsx` пока передаёт старые пропсы (`onPrev` и т.д.) — TypeScript-ошибка будет поймана в Task 6; vitest транспилирует без typecheck, тесты SentenceView проходят.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/reader/SentenceView.tsx frontend/src/features/reader/SentenceView.test.tsx
git commit -m "feat(reader): mockup sentence layout with play stub and vocab rows" -- frontend/src/features/reader/SentenceView.tsx frontend/src/features/reader/SentenceView.test.tsx
```

---

### Task 6: Стрелки навигации по краям и проводка в ReaderPage

**Files:**
- Modify: `frontend/src/features/reader/ReaderPage.tsx:356-370` (вызов SentenceView, стрелки)
- Modify: `frontend/src/features/reader/ReaderPage.test.tsx` (новый тест на стрелки)

**Interfaces:**
- Consumes: сигнатура `SentenceView` из Task 5.
- Produces: стрелки с `aria-label="Предыдущее предложение"` / `aria-label="Следующее предложение"`, видимые только в sentence-режиме.

- [ ] **Step 1: Написать падающий тест в `ReaderPage.test.tsx`**

Добавить в конец `describe('ReaderPage', ...)`:

```tsx
  it('navigates sentences with the fixed edge arrows in sentence mode', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue({
      ...baseLesson,
      reader_position: { view_mode: 'sentence', current_segment_id: 'seg-1', current_token_ordinal: 0 },
    })
    vi.mocked(readerApi.content).mockResolvedValue(content)
    vi.mocked(readerApi.statuses).mockResolvedValue({})
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })

    renderPage()

    const slot = await screen.findByTestId('sentence-view-slot')
    await waitFor(() => expect(slot).toHaveTextContent('Hello world.'))

    const prev = screen.getByRole('button', { name: 'Предыдущее предложение' })
    const next = screen.getByRole('button', { name: 'Следующее предложение' })
    expect(prev).toBeDisabled()

    fireEvent.click(next)
    await waitFor(() => expect(slot).toHaveTextContent('Goodbye now.'))
    expect(screen.getByRole('button', { name: 'Следующее предложение' })).toBeDisabled()
  })
```

Примечание: sentence-режим теперь рендерит `SentenceVocabList`, который зовёт `vocabularyApi.lookup`, поэтому мок обязателен и в тестах `restores sentence-mode position...` / `falls back to the first sentence...` — добавить тот же `vi.mocked(vocabularyApi.lookup).mockResolvedValue(...)` в эти два теста (или вынести в `beforeEach`).

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && npm test -- --run src/features/reader/ReaderPage.test.tsx`
Expected: FAIL — кнопок с такими aria-label нет.

- [ ] **Step 3: Обновить `ReaderPage.tsx`**

Заменить блок sentence-режима:

```tsx
        {!contentLoading && content && mode === 'sentence' && currentSentence && (
          <div data-testid="sentence-view-slot">
            <SentenceView
              lessonId={lessonId}
              sentence={currentSentence}
              statuses={statusMap}
              lang={content.language_code}
              targetLang={DEFAULT_TRANSLATION_LANG}
              onWordClick={setSelectedWord}
            />
          </div>
        )}
```

Сразу после закрывающего `</div>` контентной обёртки (перед `<BottomToolbar ...>`) добавить стрелки:

```tsx
      {!contentLoading && content && mode === 'sentence' && (
        <>
          <button
            type="button"
            aria-label="Предыдущее предложение"
            onClick={handlePrevSentence}
            disabled={!canPrevSentence}
            className="fixed left-2 top-1/2 z-10 -translate-y-1/2 rounded-md px-2 py-1 text-3xl text-muted-foreground hover:bg-accent disabled:pointer-events-none disabled:opacity-30"
          >
            ‹
          </button>
          <button
            type="button"
            aria-label="Следующее предложение"
            onClick={handleNextSentence}
            disabled={!canNextSentence}
            className="fixed right-2 top-1/2 z-10 -translate-y-1/2 rounded-md px-2 py-1 text-3xl text-muted-foreground hover:bg-accent disabled:pointer-events-none disabled:opacity-30"
          >
            ›
          </button>
        </>
      )}
```

- [ ] **Step 4: Прогнать тесты и typecheck**

Run: `cd frontend && npm test -- --run src/features/reader/ReaderPage.test.tsx && npx tsc -b --noEmit`
Expected: PASS, без TS-ошибок.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/reader/ReaderPage.tsx frontend/src/features/reader/ReaderPage.test.tsx
git commit -m "feat(reader): fixed edge navigation arrows in sentence mode" -- frontend/src/features/reader/ReaderPage.tsx frontend/src/features/reader/ReaderPage.test.tsx
```

---

### Task 7: Финальная верификация

**Files:** нет новых.

- [ ] **Step 1: Полный прогон тестов, линт, сборка**

Run: `cd frontend && npm test -- --run && npm run lint && npm run build`
Expected: все тесты PASS, линт без ошибок, сборка успешна.

- [ ] **Step 2: Визуальная проверка в браузере**

Запустить `npm run dev` (вместе с бэкендом через `docker-compose.dev.yml`, если не запущен), открыть урок в sentence-режиме и сверить с макетом: центрированный прогресс с точкой, Play-заглушка, левовыровненный текст 20px с подсветками `#FFEBA8`/`#C6DFFF`, подчёркнутая серая ссылка перевода, строки лексики с кружками и переводами, нижняя панель из трёх действий, стрелки по краям. Прокликать: переключение режима, клик по слову → WordCard, клик по строке лексики → WordCard.

- [ ] **Step 3: Поправить найденные визуальные огрехи (если есть) и закоммитить**

```bash
git add frontend/src/features/reader
git commit -m "style(reader): visual polish after mockup comparison" -- frontend/src/features/reader
```
