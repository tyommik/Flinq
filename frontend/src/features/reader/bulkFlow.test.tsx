import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { LessonDetail } from '@/api/lessons'
import type { LessonContent, Sentence, Token } from '@/api/reader'

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children, className }: { children?: ReactNode; className?: string }) => (
    <a className={className}>{children}</a>
  ),
}))

vi.mock('@/api/lessons', () => ({
  lessonsApi: {
    get: vi.fn(),
  },
}))

vi.mock('@/api/reader', () => ({
  isWord: (tok: { t?: string }) => 't' in tok,
  readerApi: {
    content: vi.fn(),
    statuses: vi.fn(),
    putPosition: vi.fn(),
    bulkKnown: vi.fn(),
    undoBulk: vi.fn(),
    segmentTranslation: vi.fn(),
  },
}))

import { lessonsApi } from '@/api/lessons'
import { readerApi } from '@/api/reader'

import { useReaderStore } from './readerStore'
import { ReaderPage } from './ReaderPage'

/** Builds `count` word tokens with globally increasing ordinals starting at `startOrdinal`. */
function makeWordTokens(startOrdinal: number, count: number): Token[] {
  const tokens: Token[] = []
  for (let idx = 0; idx < count; idx += 1) {
    if (idx > 0) tokens.push({ ws: ' ' })
    const ordinal = startOrdinal + idx
    tokens.push({ t: `w${ordinal}`, n: `w${ordinal}`, i: ordinal })
  }
  return tokens
}

function makeSentence(segId: string, index: number, startOrdinal: number, wordCount: number): Sentence {
  const tokens = makeWordTokens(startOrdinal, wordCount)
  return {
    seg_id: segId,
    index,
    text: tokens
      .filter((t): t is Extract<Token, { t: string }> => 't' in t)
      .map((t) => t.t)
      .join(' '),
    normalized_text: '',
    tokens: [...tokens, { p: '.' }],
  }
}

const baseLesson: LessonDetail = {
  id: 'lesson-1',
  title: 'Test Lesson',
  language_code: 'en',
  word_count: 260,
  visibility: 'private',
  status: 'ready',
  created_at: '2026-01-01T00:00:00Z',
  segment_count: 2,
  reader_position: null,
}

// Sentence 1 has exactly 250 words -> flushes as its own page (fromOrdinal 0,
// toOrdinal 249). Sentence 2 has 10 trailing words -> a second, final page
// (fromOrdinal 250, toOrdinal 259).
const sentence1 = makeSentence('seg-1', 0, 0, 250)
const sentence2 = makeSentence('seg-2', 1, 250, 10)

const content: LessonContent = {
  lesson_id: 'lesson-1',
  language_code: 'en',
  word_count: 260,
  paragraphs: [{ sentences: [sentence1, sentence2] }],
}

/**
 * TanStack Query v5 calls `mutationFn(variables, context)` — a second,
 * internal context argument is always present, so we assert on the first
 * call's first argument rather than the full call signature.
 */
function firstCallArg(mockFn: { mock: { calls: unknown[][] } }): unknown {
  return mockFn.mock.calls[0]?.[0]
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ReaderPage lang="en" lessonId="lesson-1" />
    </QueryClientProvider>,
  )
}

describe('bulk-known flow, undo, hotkeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useReaderStore.setState({
      mode: 'page',
      pageIndex: 0,
      sentenceFlatIndex: 0,
      sidebarOpen: false,
      lastBulkActionId: null,
      font: { size: 1, lineHeight: 1, serif: false },
    })
    vi.mocked(lessonsApi.get).mockResolvedValue(baseLesson)
    vi.mocked(readerApi.content).mockResolvedValue(content)
    vi.mocked(readerApi.statuses).mockResolvedValue({})
    vi.mocked(readerApi.putPosition).mockResolvedValue(undefined)
  })

  it('advances the page via bulk-known with the exact ordinal range, then undoes via the toast', async () => {
    vi.mocked(readerApi.bulkKnown).mockResolvedValue({ action_id: 'action-1', created_count: 2 })
    vi.mocked(readerApi.undoBulk).mockResolvedValue({ undone_count: 2 })

    renderPage()

    await screen.findByTestId('page-view-slot')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))

    await waitFor(() =>
      expect(firstCallArg(vi.mocked(readerApi.bulkKnown))).toEqual({
        lesson_id: 'lesson-1',
        from_ordinal: 0,
        to_ordinal: 249,
      }),
    )

    const toast = await screen.findByTestId('undo-toast')
    expect(toast).toHaveTextContent('2 слов помечены как known')

    // Page advanced to the second page (contains the first word of sentence 2).
    await waitFor(() => expect(screen.getByTestId('page-view-slot')).toHaveTextContent('w250'))

    fireEvent.click(screen.getByRole('button', { name: 'Отменить' }))

    await waitFor(() => expect(firstCallArg(vi.mocked(readerApi.undoBulk))).toEqual('action-1'))
    await waitFor(() => expect(screen.queryByTestId('undo-toast')).not.toBeInTheDocument())
  })

  it('advances without a toast when created_count is 0', async () => {
    vi.mocked(readerApi.bulkKnown).mockResolvedValue({ action_id: 'action-2', created_count: 0 })

    renderPage()

    await screen.findByTestId('page-view-slot')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))

    await waitFor(() =>
      expect(firstCallArg(vi.mocked(readerApi.bulkKnown))).toEqual({
        lesson_id: 'lesson-1',
        from_ordinal: 0,
        to_ordinal: 249,
      }),
    )

    await waitFor(() => expect(screen.getByTestId('page-view-slot')).toHaveTextContent('w250'))
    expect(screen.queryByTestId('undo-toast')).not.toBeInTheDocument()
  })

  it('toggles view mode with "m" and navigates with ArrowRight', async () => {
    renderPage()

    await screen.findByTestId('page-view-slot')

    fireEvent.keyDown(window, { key: 'm' })
    await screen.findByTestId('sentence-view-slot')
    expect(screen.getByTestId('sentence-view-slot')).toHaveTextContent('w0')

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    await waitFor(() => expect(screen.getByTestId('sentence-view-slot')).toHaveTextContent('w250'))
    expect(readerApi.bulkKnown).not.toHaveBeenCalled()
  })

  it('undoes the last bulk action with Ctrl+Z', async () => {
    vi.mocked(readerApi.bulkKnown).mockResolvedValue({ action_id: 'action-9', created_count: 3 })
    vi.mocked(readerApi.undoBulk).mockResolvedValue({ undone_count: 3 })

    renderPage()

    await screen.findByTestId('page-view-slot')
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))

    await screen.findByTestId('undo-toast')

    fireEvent.keyDown(window, { key: 'z', ctrlKey: true })

    await waitFor(() => expect(firstCallArg(vi.mocked(readerApi.undoBulk))).toEqual('action-9'))
    await waitFor(() => expect(screen.queryByTestId('undo-toast')).not.toBeInTheDocument())
  })
})
