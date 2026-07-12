import type { ComponentProps } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { Sentence, StatusMap } from '@/api/reader'

vi.mock('@/api/reader', async () => {
  const actual = await vi.importActual<typeof import('@/api/reader')>('@/api/reader')
  return {
    ...actual,
    readerApi: {
      segmentTranslation: vi.fn(),
    },
  }
})

import { readerApi } from '@/api/reader'

vi.mock('@/api/vocabulary', () => ({
  vocabularyApi: { lookup: vi.fn() },
}))

import { vocabularyApi } from '@/api/vocabulary'

import { DEFAULT_TRANSLATION_LANG, SentenceView } from './SentenceView'

const sentence: Sentence = {
  seg_id: 'seg-1',
  index: 0,
  text: 'Hello brave world.',
  normalized_text: 'hello brave world.',
  tokens: [
    { t: 'Hello', n: 'hello', i: 0 },
    { ws: ' ' },
    { t: 'brave', n: 'brave', i: 1 },
    { ws: ' ' },
    { t: 'world', n: 'world', i: 2 },
    { p: '.' },
  ],
}

const statuses: StatusMap = {
  hello: { s: 'tracked', c: 2 },
  brave: { s: 'known' },
  // 'world' intentionally statusless
}

function renderView(overrides: Partial<ComponentProps<typeof SentenceView>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onWordClick = vi.fn()
  render(
    <QueryClientProvider client={queryClient}>
      <SentenceView
        lessonId="lesson-1"
        sentence={sentence}
        statuses={statuses}
        phraseIndex={new Map()}
        dragRange={null}
        lang="en"
        targetLang={DEFAULT_TRANSLATION_LANG}
        onWordClick={onWordClick}
        {...overrides}
      />
    </QueryClientProvider>,
  )
  return { onWordClick }
}

describe('SentenceView', () => {
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

  it('does not fetch the translation before expand', () => {
    vi.mocked(readerApi.segmentTranslation).mockResolvedValue({
      text: 'Привет храбрый мир.',
      source: 'ai',
      model: 'test',
      stored: true,
    })

    renderView()

    expect(readerApi.segmentTranslation).not.toHaveBeenCalled()
  })

  it('fetches the translation exactly once, even across collapse and re-expand', async () => {
    vi.mocked(readerApi.segmentTranslation).mockResolvedValue({
      text: 'Привет храбрый мир.',
      source: 'ai',
      model: 'test',
      stored: true,
    })

    renderView()
    const toggle = screen.getByTestId('toggle-translation')

    fireEvent.click(toggle)
    await waitFor(() =>
      expect(screen.getByTestId('sentence-translation')).toHaveTextContent('Привет храбрый мир.'),
    )
    expect(readerApi.segmentTranslation).toHaveBeenCalledTimes(1)
    expect(screen.getByText('AI')).toBeInTheDocument()

    fireEvent.click(toggle) // collapse
    expect(screen.queryByTestId('sentence-translation')).not.toBeInTheDocument()

    fireEvent.click(toggle) // re-expand
    await waitFor(() =>
      expect(screen.getByTestId('sentence-translation')).toHaveTextContent('Привет храбрый мир.'),
    )
    expect(readerApi.segmentTranslation).toHaveBeenCalledTimes(1)
  })

  it('shows "Переводим…" while the translation request is pending', async () => {
    let resolvePromise: (value: {
      text: string
      source: string
      model: string
      stored: boolean
    }) => void = () => {}
    vi.mocked(readerApi.segmentTranslation).mockReturnValue(
      new Promise((resolve) => {
        resolvePromise = resolve
      }),
    )

    renderView()
    fireEvent.click(screen.getByTestId('toggle-translation'))

    expect(await screen.findByText('Переводим…')).toBeInTheDocument()
    resolvePromise({ text: 'done', source: 'human', model: '', stored: true })
  })

  it('shows an AI-disabled message for a 503 error, with no retry button', async () => {
    vi.mocked(readerApi.segmentTranslation).mockRejectedValue(new ApiError(503, 'disabled'))

    renderView()
    fireEvent.click(screen.getByTestId('toggle-translation'))

    expect(await screen.findByText('AI отключён администратором')).toBeInTheDocument()
    expect(screen.queryByText('Повторить')).not.toBeInTheDocument()
  })

  it('shows a generic failure message with a retry button for other errors', async () => {
    vi.mocked(readerApi.segmentTranslation).mockRejectedValue(new ApiError(502, 'bad gateway'))

    renderView()
    fireEvent.click(screen.getByTestId('toggle-translation'))

    expect(await screen.findByText('Не удалось перевести')).toBeInTheDocument()
    expect(screen.getByText('Повторить')).toBeInTheDocument()
  })

  it('does not render a translation without source ai badge for non-ai source', async () => {
    vi.mocked(readerApi.segmentTranslation).mockResolvedValue({
      text: 'Human translation',
      source: 'human',
      model: '',
      stored: true,
    })

    renderView()
    fireEvent.click(screen.getByTestId('toggle-translation'))

    await screen.findByText('Human translation')
    expect(screen.queryByText('AI')).not.toBeInTheDocument()
  })

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
})
