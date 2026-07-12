import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/vocabulary', () => ({
  vocabularyApi: {
    lookup: vi.fn(), createItem: vi.fn(), patchItem: vi.fn(),
    addTranslation: vi.fn(), updateTranslation: vi.fn(), deleteTranslation: vi.fn(),
    putNote: vi.fn(), addTag: vi.fn(), removeTag: vi.fn(),
  },
}))
vi.mock('@/api/dictionary', () => ({ dictionaryApi: { lookup: vi.fn() } }))
vi.mock('@/api/ai', () => ({ aiApi: { translate: vi.fn() } }))

import { vocabularyApi } from '@/api/vocabulary'
import { dictionaryApi } from '@/api/dictionary'
import { aiApi } from '@/api/ai'
import { ApiError } from '@/api/client'
import { useReaderStore } from './readerStore'
import { WordCard } from './WordCard'

function renderCard(sentenceText: string | null = null, lessonId: string | null = 'L1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <WordCard
        word={{ kind: 'token', t: 'cada', n: 'cada', i: 0, sentenceText: null }}
        lang="pt" target="ru" lessonId={lessonId} onClose={() => {}}
        sentenceText={sentenceText}
      />
    </QueryClientProvider>,
  )
}

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('WordCard core', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(dictionaryApi.lookup).mockResolvedValue({ entries: [], attribution: { source: '', license: '', url: '' }, external_links: [] })
    vi.mocked(aiApi.translate).mockResolvedValue({ hints: [], model: '', latency_ms: 0 })
    // wordCardExpanded lives in the module-level reader store now (not local
    // useState), so it leaks across tests in this file unless reset.
    useReaderStore.setState({ wordCardExpanded: false })
  })

  it('creates a tracked/0 item when a translation is typed on a new word', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(vocabularyApi.createItem).mockResolvedValue({ item_id: 'I1', status: 'tracked', confidence: 0 })
    vi.mocked(vocabularyApi.addTranslation).mockResolvedValue({ id: 'T1', text: 'каждый', target_language_code: 'ru', is_primary: true, source_type: 'user' })

    renderCard()
    const input = await screen.findByPlaceholderText('Введите новый перевод здесь')
    fireEvent.change(input, { target: { value: 'каждый' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => {
      expect(vocabularyApi.createItem).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'tracked', confidence: 0, text: 'cada' }),
      )
    })
    await waitFor(() => {
      expect(vocabularyApi.addTranslation).toHaveBeenCalledWith(
        'token', 'I1', expect.objectContaining({ translation_text: 'каждый' }),
      )
    })
  })

  it('does not fire status hotkeys while typing in the translation input', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })

    renderCard()
    const input = await screen.findByPlaceholderText('Введите новый перевод здесь')
    // wait for the lookup to resolve (footer only renders once `data` is loaded,
    // which is also the gate that guards the status hotkeys)
    await screen.findByRole('button', { name: 'Игнорировать' })

    fireEvent.change(input, { target: { value: 'kill' } })
    fireEvent.keyDown(input, { key: 'k' })
    fireEvent.keyDown(input, { key: 'i' })
    fireEvent.keyDown(input, { key: '1' })

    // mutate() dispatches asynchronously, so give it a tick before asserting
    // it never fired as a side effect of typing.
    await new Promise((r) => setTimeout(r, 50))
    expect(vocabularyApi.createItem).not.toHaveBeenCalled()
    expect(vocabularyApi.patchItem).not.toHaveBeenCalled()
  })

  it('sets confidence via the footer pill on an existing tracked item', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'tracked', confidence: 0,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(vocabularyApi.patchItem).mockResolvedValue({ item_id: 'I1', status: 'tracked', confidence: 2 })

    renderCard()
    const pill = await screen.findByRole('button', { name: 'Уровень 2' })
    fireEvent.click(pill)
    await waitFor(() => {
      expect(vocabularyApi.patchItem).toHaveBeenCalledWith('token', 'I1', { status: 'tracked', confidence: 2 })
    })
  })

  it('shows a Wiktionary suggestion and saves it as primary on +', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'tracked', confidence: 1,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(dictionaryApi.lookup).mockResolvedValue({
      entries: [{ headword: 'cada', part_of_speech: 'det', senses: [
        { sense_index: 0, translation: 'каждый', usage_note: null, examples: [] },
      ] }],
      attribution: { source: 'Wiktionary', license: 'CC BY-SA', url: '' },
      external_links: [],
    })
    vi.mocked(vocabularyApi.addTranslation).mockResolvedValue({ id: 'T1', text: 'каждый', target_language_code: 'ru', is_primary: true, source_type: 'dictionary' })

    renderCard()
    const add = await screen.findByRole('button', { name: 'Добавить перевод (📘): каждый' })
    fireEvent.click(add)
    await waitFor(() => {
      expect(vocabularyApi.addTranslation).toHaveBeenCalledWith(
        'token', 'I1', expect.objectContaining({ translation_text: 'каждый', source_type: 'dictionary' }),
      )
    })
  })

  it('requests AI for known words but not for tracked ones', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'known', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    renderCard()
    await waitFor(() => expect(aiApi.translate).toHaveBeenCalled())

    vi.clearAllMocks()
    vi.mocked(dictionaryApi.lookup).mockResolvedValue({ entries: [], attribution: { source: '', license: '', url: '' }, external_links: [] })
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I2', status: 'tracked', confidence: 1,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    renderCard()
    await screen.findAllByText('cada')
    await new Promise((r) => setTimeout(r, 50))
    expect(aiApi.translate).not.toHaveBeenCalled()
  })

  it('passes the sentence as AI context when provided', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    renderCard('Cada casa tem uma porta.')
    await waitFor(() => {
      expect(aiApi.translate).toHaveBeenCalledWith(
        expect.objectContaining({ surface_text: 'cada', context_text: 'Cada casa tem uma porta.' }),
      )
    })
  })

  it('shows an info note without retry when AI is disabled (503)', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(aiApi.translate).mockRejectedValue(new ApiError(503, 'disabled'))
    renderCard()
    await screen.findByText('AI-переводы отключены')
    expect(screen.queryByText('Не удалось получить AI-перевод')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Повторить' })).not.toBeInTheDocument()
  })

  it('shows an inline error with retry on a real AI failure', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(aiApi.translate)
      .mockRejectedValueOnce(new ApiError(500, 'boom'))
      .mockResolvedValueOnce({ hints: [{ text: 'каждый' }], model: 'm', latency_ms: 1 })
    renderCard()
    await screen.findByText('Не удалось получить AI-перевод')
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    await screen.findByText(/каждый/)
  })

  it('surfaces an inline error and retries on the next blur after a failed save', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(vocabularyApi.createItem)
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ item_id: 'I1', status: 'tracked', confidence: 0 })
    vi.mocked(vocabularyApi.addTranslation).mockResolvedValue({ id: 'T1', text: 'каждый', target_language_code: 'ru', is_primary: true, source_type: 'user' })

    renderCard()
    const input = await screen.findByPlaceholderText('Введите новый перевод здесь')
    fireEvent.change(input, { target: { value: 'каждый' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => {
      expect(vocabularyApi.createItem).toHaveBeenCalledTimes(1)
    })
    await screen.findByText('Не удалось сохранить')
    expect(vocabularyApi.addTranslation).not.toHaveBeenCalled()

    // Retry: the ref was reset on failure, so the next blur re-attempts the save.
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => {
      expect(vocabularyApi.createItem).toHaveBeenCalledTimes(2)
    })
    await waitFor(() => {
      expect(vocabularyApi.addTranslation).toHaveBeenCalledWith(
        'token', 'I1', expect.objectContaining({ translation_text: 'каждый' }),
      )
    })
    await waitFor(() => {
      expect(screen.queryByText('Не удалось сохранить')).not.toBeInTheDocument()
    })
  })

  it('creates a tracked/0 item when a note is typed on a new word', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(vocabularyApi.createItem).mockResolvedValue({ item_id: 'I1', status: 'tracked', confidence: 0 })
    vi.mocked(vocabularyApi.putNote).mockResolvedValue({ note: 'моя заметка' })

    renderCard()
    const expandBtn = await screen.findByRole('button', { name: 'Развернуть' })
    fireEvent.click(expandBtn)

    // The notes textarea has no accessible name; find it among all textboxes.
    const notes = (await screen.findAllByRole('textbox')).find((el) => el.tagName === 'TEXTAREA')!
    fireEvent.change(notes, { target: { value: 'моя заметка' } })
    fireEvent.blur(notes)

    await waitFor(() => {
      expect(vocabularyApi.createItem).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'tracked', confidence: 0, text: 'cada' }),
      )
    })
    await waitFor(() => {
      expect(vocabularyApi.putNote).toHaveBeenCalledWith('token', 'I1', 'моя заметка')
    })
  })

  it('renders saved variants as fields and keeps them out of suggestions', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'tracked', confidence: 1,
      translations: {
        primary: { id: 'T1', text: 'первый', target_language_code: 'ru', is_primary: true, source_type: 'user' },
        all: [
          { id: 'T1', text: 'первый', target_language_code: 'ru', is_primary: true, source_type: 'user' },
          { id: 'T2', text: 'второй', target_language_code: 'ru', is_primary: false, source_type: 'user' },
        ],
      },
      note: null, tags: [],
    })
    renderCard()
    expect(await screen.findByDisplayValue('первый')).toBeInTheDocument()
    expect(await screen.findByDisplayValue('второй')).toBeInTheDocument()
    expect(screen.queryByText('Подсказки')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Добавить перевод .*: первый/ })).not.toBeInTheDocument()
  })

  it('deletes a variant via its ✕ button', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'tracked', confidence: 1,
      translations: {
        primary: { id: 'T1', text: 'первый', target_language_code: 'ru', is_primary: true, source_type: 'user' },
        all: [{ id: 'T1', text: 'первый', target_language_code: 'ru', is_primary: true, source_type: 'user' }],
      },
      note: null, tags: [],
    })
    vi.mocked(vocabularyApi.deleteTranslation).mockResolvedValue({ translations: [] })
    renderCard()
    const del = await screen.findByRole('button', { name: 'Удалить вариант: первый' })
    fireEvent.click(del)
    await waitFor(() => {
      expect(vocabularyApi.deleteTranslation).toHaveBeenCalledWith('token', 'I1', 'T1')
    })
  })

  it('shows the ignored layout with a reactivation hint and no editing blocks', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'ignored', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    renderCard()
    await screen.findByText('Игнорируется')
    expect(screen.getByText('Выберите уровень 1–4 или ✓, чтобы вернуть слово в изучение')).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Введите новый перевод здесь')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Развернуть' })).not.toBeInTheDocument()
    // footer stays for reactivation
    expect(screen.getByRole('button', { name: 'Уровень 1' })).toBeInTheDocument()
  })

  it('persists the expanded state across card reopen via the reader store', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'tracked', confidence: 1,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    const { unmount } = renderCard()
    fireEvent.click(await screen.findByRole('button', { name: 'Развернуть' }))
    await screen.findByText('Теги')
    unmount()
    renderCard()
    expect(await screen.findByText('Теги')).toBeInTheDocument()
    // restore the default for other tests
    fireEvent.click(screen.getByRole('button', { name: 'Свернуть' }))
  })

  it('renders and omits lesson_id from the AI request when lessonId is null (vocabulary page reuse)', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })

    renderCard(null, null)

    expect(await screen.findByTestId('word-card')).toBeInTheDocument()
    await waitFor(() => {
      expect(aiApi.translate).toHaveBeenCalled()
    })
    // The request must not carry a real lesson_id value (it's omitted from
    // the wire body via JSON.stringify dropping `undefined`).
    expect(aiApi.translate).not.toHaveBeenCalledWith(
      expect.objectContaining({ lesson_id: expect.anything() }),
    )
  })

  it('phrase card: no dictionary lookup, creates item with kind=phrase', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    vi.mocked(vocabularyApi.createItem).mockResolvedValue({ item_id: 'I1', status: 'tracked', confidence: 0 })

    render(
      <WordCard
        word={{ kind: 'phrase', t: 'so far, so good', n: 'so far so good', i: 10, sentenceText: 'So far, so good it is.' }}
        lang="en" target="ru" lessonId="l1" onClose={() => {}} sentenceText={null}
      />,
      { wrapper },
    )
    expect(await screen.findByText('so far, so good')).toBeInTheDocument()
    expect(dictionaryApi.lookup).not.toHaveBeenCalled()
    // выставляем статус — создание item уходит с kind=phrase
    fireEvent.click(await screen.findByRole('button', { name: 'Уровень 1' }))
    await waitFor(() =>
      expect(vocabularyApi.createItem).toHaveBeenCalledWith(
        expect.objectContaining({ kind: 'phrase', text: 'so far so good' }),
      ),
    )
  })

  it('token card still queries the dictionary', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: null, status: 'new', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })

    render(
      <WordCard
        word={{ kind: 'token', t: 'far', n: 'far', i: 1, sentenceText: null }}
        lang="en" target="ru" lessonId="l1" onClose={() => {}} sentenceText="It is far."
      />,
      { wrapper },
    )
    await waitFor(() => expect(dictionaryApi.lookup).toHaveBeenCalled())
  })
})
