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

    const vocab = screen.getByTestId('sentence-vocab')
    expect(vocab.querySelectorAll('li').length).toBe(2)
    // The translation subtitle span uses this exact class combination; it must be
    // absent entirely (not just empty) when there is no primary translation.
    expect(vocab.querySelectorAll('.text-sm.text-muted-foreground').length).toBe(0)
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
