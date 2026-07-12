import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { LessonDetail } from '@/api/lessons'
import type { LessonContent } from '@/api/reader'

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

vi.mock('@/api/vocabulary', () => ({
  vocabularyApi: {
    lookup: vi.fn(), createItem: vi.fn(), patchItem: vi.fn(),
    addTranslation: vi.fn(), updateTranslation: vi.fn(), deleteTranslation: vi.fn(),
    putNote: vi.fn(), addTag: vi.fn(), removeTag: vi.fn(),
  },
}))
vi.mock('@/api/dictionary', () => ({ dictionaryApi: { lookup: vi.fn() } }))
vi.mock('@/api/ai', () => ({ aiApi: { translate: vi.fn() } }))

import { lessonsApi } from '@/api/lessons'
import { readerApi } from '@/api/reader'
import { vocabularyApi } from '@/api/vocabulary'
import { dictionaryApi } from '@/api/dictionary'
import { aiApi } from '@/api/ai'

import { useReaderStore } from './readerStore'
import { ReaderPage } from './ReaderPage'

const baseLesson: LessonDetail = {
  id: 'lesson-1',
  title: 'Test Lesson',
  language_code: 'en',
  word_count: 4,
  visibility: 'private',
  status: 'ready',
  created_at: '2026-01-01T00:00:00Z',
  segment_count: 1,
  reader_position: null,
}

const content: LessonContent = {
  lesson_id: 'lesson-1',
  language_code: 'en',
  word_count: 4,
  paragraphs: [
    {
      sentences: [
        {
          seg_id: 'seg-1',
          index: 0,
          text: 'Hello world.',
          normalized_text: 'hello world.',
          tokens: [
            { t: 'Hello', n: 'hello', i: 0 },
            { ws: ' ' },
            { t: 'world', n: 'world', i: 1 },
            { p: '.' },
          ],
        },
        {
          seg_id: 'seg-2',
          index: 1,
          text: 'Goodbye now.',
          normalized_text: 'goodbye now.',
          tokens: [
            { t: 'Goodbye', n: 'goodbye', i: 2 },
            { ws: ' ' },
            { t: 'now', n: 'now', i: 3 },
            { p: '.' },
          ],
        },
      ],
    },
  ],
}

function renderPage(lessonId = 'lesson-1', queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={queryClient}>
      <ReaderPage lang="en" lessonId={lessonId} />
    </QueryClientProvider>,
  )
}

describe('ReaderPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useReaderStore.setState({
      mode: 'page',
      pageIndex: 0,
      sentenceFlatIndex: 0,
      sidebarOpen: false,
      lastBulkActionId: null,
      font: { size: 1, lineHeight: 1, serif: false },
      wordCardExpanded: false,
    })
  })

  it('shows processing state and does not fetch reader content', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue({ ...baseLesson, status: 'processing' })

    renderPage()

    expect(await screen.findByTestId('reader-processing')).toHaveTextContent('Урок готовится')
    expect(readerApi.content).not.toHaveBeenCalled()
  })

  it('shows failed state with a link back to the library', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue({ ...baseLesson, status: 'failed' })

    renderPage()

    expect(await screen.findByTestId('reader-failed')).toHaveTextContent('Не удалось обработать урок')
  })

  it('shows an unavailable state with a link back to the library for archived lessons', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue({ ...baseLesson, status: 'archived' })

    renderPage()

    expect(await screen.findByTestId('reader-unavailable')).toHaveTextContent('Урок недоступен')
    expect(readerApi.content).not.toHaveBeenCalled()
  })

  it('renders lesson words for a ready lesson', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue(baseLesson)
    vi.mocked(readerApi.content).mockResolvedValue(content)
    vi.mocked(readerApi.statuses).mockResolvedValue({})

    renderPage()

    const slot = await screen.findByTestId('page-view-slot')
    await waitFor(() => expect(slot).toHaveTextContent('Hello world.'))
    expect(slot).toHaveTextContent('Goodbye now.')
  })

  it('restores sentence-mode position to the segment referenced by current_segment_id', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue({
      ...baseLesson,
      reader_position: { view_mode: 'sentence', current_segment_id: 'seg-2', current_token_ordinal: 2 },
    })
    vi.mocked(readerApi.content).mockResolvedValue(content)
    vi.mocked(readerApi.statuses).mockResolvedValue({})
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })

    renderPage()

    const slot = await screen.findByTestId('sentence-view-slot')
    await waitFor(() => expect(slot).toHaveTextContent('Goodbye now.'))
    expect(slot).not.toHaveTextContent('Hello world.')
  })

  it('falls back to the first sentence when current_segment_id is not found', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue({
      ...baseLesson,
      reader_position: { view_mode: 'sentence', current_segment_id: 'seg-missing', current_token_ordinal: 0 },
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
  })

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

  it('shows an error state and does not spin forever when the lesson fetch fails', async () => {
    vi.mocked(lessonsApi.get).mockRejectedValue(new Error('network error'))

    renderPage()

    expect(await screen.findByTestId('reader-error')).toHaveTextContent('Не удалось загрузить урок')
    expect(readerApi.content).not.toHaveBeenCalled()
  })

  it('resets pageIndex and disarms the undo action when the lesson changes', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue(baseLesson)
    vi.mocked(readerApi.content).mockResolvedValue(content)
    vi.mocked(readerApi.statuses).mockResolvedValue({})

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { rerender } = renderPage('lesson-1', queryClient)

    await screen.findByTestId('page-view-slot')

    act(() => {
      useReaderStore.setState({ pageIndex: 1, lastBulkActionId: 'stale-action' })
    })

    vi.mocked(lessonsApi.get).mockResolvedValue({ ...baseLesson, id: 'lesson-2' })

    rerender(
      <QueryClientProvider client={queryClient}>
        <ReaderPage lang="en" lessonId="lesson-2" />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(useReaderStore.getState().lastBulkActionId).toBeNull()
      expect(useReaderStore.getState().pageIndex).toBe(0)
    })
    await screen.findByTestId('page-view-slot')
  })

  it('opens the real WordCard when a word is clicked', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue(baseLesson)
    vi.mocked(readerApi.content).mockResolvedValue(content)
    vi.mocked(readerApi.statuses).mockResolvedValue({})
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(dictionaryApi.lookup).mockResolvedValue({
      entries: [], attribution: { source: '', license: '', url: '' }, external_links: [],
    })
    vi.mocked(aiApi.translate).mockResolvedValue({ hints: [], model: '', latency_ms: 0 })

    renderPage()

    await screen.findByTestId('page-view-slot')
    fireEvent.click(await screen.findByRole('button', { name: 'Hello' }))
    expect(await screen.findByTestId('word-card')).toBeInTheDocument()
    expect(await screen.findByPlaceholderText('Введите новый перевод здесь')).toBeInTheDocument()
  })
})
