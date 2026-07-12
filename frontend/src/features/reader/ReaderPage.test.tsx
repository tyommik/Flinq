if (typeof window !== 'undefined' && !window.PointerEvent) {
  class PointerEventPolyfill extends MouseEvent {
    pointerType: string
    constructor(type: string, init: MouseEventInit & { pointerType?: string } = {}) {
      super(type, init)
      this.pointerType = init.pointerType ?? 'mouse'
    }
  }
  window.PointerEvent = PointerEventPolyfill as unknown as typeof PointerEvent
}

import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { LessonDetail } from '@/api/lessons'
import type { LessonContent } from '@/api/reader'

const { navigateMock } = vi.hoisted(() => ({ navigateMock: vi.fn() }))

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => navigateMock,
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
    phrases: vi.fn(),
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
    vi.mocked(vocabularyApi.phrases).mockResolvedValue([])
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
    vi.mocked(readerApi.bulkKnown).mockResolvedValue({ action_id: 'action-1', created_count: 2 })
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

  it('renders saved phrase underlay and opens phrase card on click', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue(baseLesson)
    vi.mocked(readerApi.content).mockResolvedValue(content)
    vi.mocked(readerApi.statuses).mockResolvedValue({})
    vi.mocked(vocabularyApi.phrases).mockResolvedValue([
      { item_id: 'ph1', phrase_text: 'hello world', status: 'tracked', confidence: 1 },
    ])
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'ph1', status: 'tracked', confidence: 1,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })

    renderPage()

    const phrase = await screen.findByTestId('phrase-span')
    fireEvent.click(phrase)
    expect(await screen.findByTestId('word-card')).toBeInTheDocument()
  })

  it('keeps the clicked word highlighted while its card is open and clears on close', async () => {
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
    const hello = await screen.findByRole('button', { name: 'Hello' })
    fireEvent.click(hello)
    const card = await screen.findByTestId('word-card')

    expect(hello.className).toContain('bg-primary/20')
    expect(screen.getByRole('button', { name: 'world' }).className).not.toContain('bg-primary/20')

    fireEvent.click(within(card).getByRole('button', { name: 'Закрыть' }))
    expect(screen.queryByTestId('word-card')).not.toBeInTheDocument()
    expect(hello.className).not.toContain('bg-primary/20')
  })

  it('keeps the dragged phrase highlighted while its card is open', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue(baseLesson)
    vi.mocked(readerApi.content).mockResolvedValue(content)
    vi.mocked(readerApi.statuses).mockResolvedValue({})
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(aiApi.translate).mockResolvedValue({ hints: [], model: '', latency_ms: 0 })

    renderPage()

    await screen.findByTestId('page-view-slot')
    const hello = screen.getByRole('button', { name: 'Hello' })
    const world = screen.getByRole('button', { name: 'world' })

    fireEvent(
      hello,
      new PointerEvent('pointerdown', { bubbles: true, pointerType: 'mouse', button: 0, buttons: 1 }),
    )
    fireEvent(
      world,
      new PointerEvent('pointerover', { bubbles: true, pointerType: 'mouse', button: 0, buttons: 1 }),
    )
    fireEvent(
      world,
      new PointerEvent('pointerup', { bubbles: true, pointerType: 'mouse', button: 0, buttons: 0 }),
    )

    const card = await screen.findByTestId('word-card')
    expect(hello.className).toContain('bg-primary/20')
    expect(world.className).toContain('bg-primary/20')

    fireEvent.click(within(card).getByRole('button', { name: 'Закрыть' }))
    expect(hello.className).not.toContain('bg-primary/20')
    expect(world.className).not.toContain('bg-primary/20')
  })

  it('clears the selection highlight when a status is applied but keeps the card open', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue(baseLesson)
    vi.mocked(readerApi.content).mockResolvedValue(content)
    vi.mocked(readerApi.statuses).mockResolvedValue({})
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(vocabularyApi.createItem).mockResolvedValue({
      item_id: 't1', status: 'tracked', confidence: 1,
    })
    vi.mocked(dictionaryApi.lookup).mockResolvedValue({
      entries: [], attribution: { source: '', license: '', url: '' }, external_links: [],
    })
    vi.mocked(aiApi.translate).mockResolvedValue({ hints: [], model: '', latency_ms: 0 })

    renderPage()

    await screen.findByTestId('page-view-slot')
    const hello = await screen.findByRole('button', { name: 'Hello' })
    fireEvent.click(hello)
    await screen.findByTestId('word-card')
    expect(hello.className).toContain('bg-primary/20')

    fireEvent.click(await screen.findByRole('button', { name: 'Уровень 1' }))

    await waitFor(() => expect(hello.className).not.toContain('bg-primary/20'))
    expect(screen.getByTestId('word-card')).toBeInTheDocument()
  })

  it('Escape during an active phrase drag cancels the drag instead of navigating to the library', async () => {
    vi.mocked(lessonsApi.get).mockResolvedValue(baseLesson)
    vi.mocked(readerApi.content).mockResolvedValue(content)
    vi.mocked(readerApi.statuses).mockResolvedValue({})

    renderPage()

    await screen.findByTestId('page-view-slot')

    const helloWord = screen.getByRole('button', { name: 'Hello' })
    const worldWord = screen.getByRole('button', { name: 'world' })

    fireEvent(
      helloWord,
      new PointerEvent('pointerdown', { bubbles: true, pointerType: 'mouse', button: 0, buttons: 1 }),
    )
    fireEvent(
      worldWord,
      new PointerEvent('pointerover', { bubbles: true, pointerType: 'mouse', button: 0, buttons: 1 }),
    )

    fireEvent.keyDown(window, { key: 'Escape' })

    // The drag was cancelled (not finalized into a phrase selection), and the
    // reader did NOT navigate away to the library — only the drag was cancelled.
    expect(navigateMock).not.toHaveBeenCalled()
    expect(screen.getByTestId('page-view-slot')).toBeInTheDocument()

    fireEvent(
      worldWord,
      new PointerEvent('pointerup', { bubbles: true, pointerType: 'mouse', button: 0, buttons: 0 }),
    )
    expect(screen.queryByTestId('word-card')).not.toBeInTheDocument()
  })
})
