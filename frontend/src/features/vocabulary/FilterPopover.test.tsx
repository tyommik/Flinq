import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { FilterPopover } from './FilterPopover'
import { useVocabularyStore } from './vocabularyStore'

const DEFAULT_STATUSES: ('tracked' | 'known' | 'ignored')[] = ['tracked', 'known', 'ignored']

function resetStore() {
  useVocabularyStore.setState({
    q: '',
    statuses: DEFAULT_STATUSES,
    confidence: null,
    tags: [],
    addedPreset: 'all',
    sort: 'created_at',
    sortDir: 'desc',
    page: 1,
    pageSize: 25,
    selection: [],
    showAuto: false,
  })
}

describe('FilterPopover', () => {
  beforeEach(() => {
    resetStore()
  })

  it('is closed by default and opens the panel on trigger click', () => {
    render(<FilterPopover />)
    expect(screen.queryByText('Уровень уверенности')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '⊟ Фильтры' }))

    expect(screen.getByText('Уровень уверенности')).toBeInTheDocument()
  })

  it('unchecking a status checkbox calls setStatuses with the updated array', () => {
    render(<FilterPopover />)
    fireEvent.click(screen.getByRole('button', { name: '⊟ Фильтры' }))

    fireEvent.click(screen.getByRole('checkbox', { name: 'Изученные' }))

    expect(useVocabularyStore.getState().statuses).toEqual(['tracked', 'ignored'])
  })

  it('Enter in the tag input adds a chip and calls setTags', () => {
    render(<FilterPopover />)
    fireEvent.click(screen.getByRole('button', { name: '⊟ Фильтры' }))

    const input = screen.getByPlaceholderText('Добавить тег…')
    fireEvent.change(input, { target: { value: 'verbs' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(useVocabularyStore.getState().tags).toEqual(['verbs'])
    expect(screen.getByText('verbs')).toBeInTheDocument()
  })

  it('clicking a tag chip removes it', () => {
    useVocabularyStore.setState({ tags: ['verbs'] })
    render(<FilterPopover />)
    fireEvent.click(screen.getByRole('button', { name: '⊟ Фильтры' }))

    fireEvent.click(screen.getByRole('button', { name: 'Удалить тег verbs' }))

    expect(useVocabularyStore.getState().tags).toEqual([])
  })

  it('«Сбросить» calls resetFilters', () => {
    useVocabularyStore.setState({ statuses: ['tracked'], tags: ['verbs'], q: 'abc' })
    render(<FilterPopover />)
    fireEvent.click(screen.getByRole('button', { name: '⊟ Фильтры' }))

    fireEvent.click(screen.getByRole('button', { name: 'Сбросить' }))

    const state = useVocabularyStore.getState()
    expect(state.statuses).toEqual(DEFAULT_STATUSES)
    expect(state.tags).toEqual([])
    expect(state.q).toBe('')
  })

  it('checking «Показывать авто-изученные» calls setShowAuto(true)', () => {
    render(<FilterPopover />)
    fireEvent.click(screen.getByRole('button', { name: '⊟ Фильтры' }))

    expect(screen.getByText('слова, отмеченные изученными при листании')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: /Показывать авто-изученные/ }))

    expect(useVocabularyStore.getState().showAuto).toBe(true)
  })

  it('«Сбросить» resets showAuto to false', () => {
    useVocabularyStore.setState({ showAuto: true })
    render(<FilterPopover />)
    fireEvent.click(screen.getByRole('button', { name: '⊟ Фильтры' }))

    fireEvent.click(screen.getByRole('button', { name: 'Сбросить' }))

    expect(useVocabularyStore.getState().showAuto).toBe(false)
  })

  it('confidence selects are disabled when «Отслеживаемые» is unchecked', () => {
    useVocabularyStore.setState({ statuses: ['known', 'ignored'] })
    render(<FilterPopover />)
    fireEvent.click(screen.getByRole('button', { name: '⊟ Фильтры' }))

    expect(screen.getByLabelText('Уверенность от')).toBeDisabled()
    expect(screen.getByLabelText('Уверенность до')).toBeDisabled()
  })

  it('confidence selects are enabled when «Отслеживаемые» is checked', () => {
    render(<FilterPopover />)
    fireEvent.click(screen.getByRole('button', { name: '⊟ Фильтры' }))

    expect(screen.getByLabelText('Уверенность от')).not.toBeDisabled()
    expect(screen.getByLabelText('Уверенность до')).not.toBeDisabled()
  })

  it('closes when clicking outside the panel', () => {
    render(
      <div>
        <div data-testid="outside">outside</div>
        <FilterPopover />
      </div>,
    )
    fireEvent.click(screen.getByRole('button', { name: '⊟ Фильтры' }))
    expect(screen.getByText('Уровень уверенности')).toBeInTheDocument()

    fireEvent.mouseDown(screen.getByTestId('outside'))

    expect(screen.queryByText('Уровень уверенности')).not.toBeInTheDocument()
  })
})
