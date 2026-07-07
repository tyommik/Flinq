import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/vocabulary', () => ({
  vocabularyApi: {
    lookup: vi.fn(), createItem: vi.fn(), patchItem: vi.fn(),
    addTranslation: vi.fn(), putNote: vi.fn(), addTag: vi.fn(), removeTag: vi.fn(),
  },
}))
vi.mock('@/api/dictionary', () => ({ dictionaryApi: { lookup: vi.fn() } }))
vi.mock('@/api/ai', () => ({ aiApi: { translate: vi.fn() } }))

import { vocabularyApi } from '@/api/vocabulary'
import { dictionaryApi } from '@/api/dictionary'
import { aiApi } from '@/api/ai'
import { WordCard } from './WordCard'

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <WordCard
        word={{ t: 'cada', n: 'cada', i: 0 }}
        lang="pt" target="ru" lessonId="L1" onClose={() => {}}
      />
    </QueryClientProvider>,
  )
}

describe('WordCard core', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(dictionaryApi.lookup).mockResolvedValue({ entries: [], attribution: { source: '', license: '', url: '' }, external_links: [] })
    vi.mocked(aiApi.translate).mockResolvedValue({ hints: [], model: '', latency_ms: 0 })
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
    fireEvent.blur(input)

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
    const add = await screen.findByRole('button', { name: 'Добавить перевод: каждый' })
    fireEvent.click(add)
    await waitFor(() => {
      expect(vocabularyApi.addTranslation).toHaveBeenCalledWith(
        'token', 'I1', expect.objectContaining({ translation_text: 'каждый', source_type: 'dictionary' }),
      )
    })
  })

  it('does not call AI for a non-new word', async () => {
    vi.mocked(vocabularyApi.lookup).mockResolvedValue({
      item_id: 'I1', status: 'known', confidence: null,
      translations: { primary: null, all: [] }, note: null, tags: [],
    })
    renderCard()
    await screen.findByText('cada')
    const { aiApi } = await import('@/api/ai')
    expect(aiApi.translate).not.toHaveBeenCalled()
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
    fireEvent.blur(input)

    await waitFor(() => {
      expect(vocabularyApi.createItem).toHaveBeenCalledTimes(1)
    })
    await screen.findByText('Не удалось сохранить')
    expect(vocabularyApi.addTranslation).not.toHaveBeenCalled()

    // Retry: the ref was reset on failure, so the next blur re-attempts the save.
    fireEvent.blur(input)

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
})
