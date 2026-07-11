import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { VocabListItem } from '@/api/vocabulary'
import { VocabularyTable } from './VocabularyTable'

const enriched: VocabListItem = {
  item_id: 'i1',
  kind: 'token',
  text: 'abaixaram',
  status: 'tracked',
  confidence: 2,
  primary_translation: { text: 'опустили', target_language_code: 'ru' },
  tags: ['verbs'],
  pos: 'verb',
  context:
    'Sacerdotes e fiéis abaixaram a cabeça diante do altar durante toda a longa cerimônia solene.',
  created_at: '2026-01-01T00:00:00Z',
}

const bare: VocabListItem = {
  item_id: 'i2',
  kind: 'token',
  text: 'casa',
  status: 'tracked',
  confidence: null,
  primary_translation: null,
  tags: [],
  pos: null,
  context: null,
  created_at: '2026-01-01T00:00:00Z',
}

function setup(items: VocabListItem[] = [enriched, bare]) {
  const onToggleSelected = vi.fn()
  const onSelectPage = vi.fn()
  const onClearSelection = vi.fn()
  const onPick = vi.fn()
  const onOpenTerm = vi.fn()
  render(
    <VocabularyTable
      items={items}
      selection={[]}
      onToggleSelected={onToggleSelected}
      onSelectPage={onSelectPage}
      onClearSelection={onClearSelection}
      onPick={onPick}
      onOpenTerm={onOpenTerm}
    />,
  )
  return { onToggleSelected, onSelectPage, onClearSelection, onPick, onOpenTerm }
}

describe('VocabularyTable', () => {
  it('renders both rows, with «—» for the missing translation', () => {
    setup()
    expect(screen.getByRole('button', { name: 'abaixaram' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'casa' })).toBeInTheDocument()
    expect(screen.getByText('опустили')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('renders uppercase column headers, including ИСХОДНЫЙ ТЕКСТ and СТАТУС', () => {
    setup()
    expect(screen.getByText('ТЕРМИН')).toBeInTheDocument()
    expect(screen.getByText('ПЕРЕВОД')).toBeInTheDocument()
    expect(screen.getByText('ИСХОДНЫЙ ТЕКСТ')).toBeInTheDocument()
    expect(screen.getByText('СТАТУС')).toBeInTheDocument()
  })

  it('fires onOpenTerm with the item when the term button is clicked', () => {
    const { onOpenTerm } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'abaixaram' }))
    expect(onOpenTerm).toHaveBeenCalledWith(enriched)
  })

  it('fires onPick(id, "tracked", 3) when «Уровень 3» is clicked in a row', () => {
    const { onPick } = setup()
    const levelThreeButtons = screen.getAllByRole('button', { name: 'Уровень 3' })
    fireEvent.click(levelThreeButtons[0]!)
    expect(onPick).toHaveBeenCalledWith('i1', 'tracked', 3)
  })

  it('header checkbox fires onSelectPage with both ids', () => {
    const { onSelectPage } = setup()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать все на странице' }))
    expect(onSelectPage).toHaveBeenCalledWith(['i1', 'i2'])
  })

  it('row checkbox fires onToggleSelected(id)', () => {
    const { onToggleSelected } = setup()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать abaixaram' }))
    expect(onToggleSelected).toHaveBeenCalledWith('i1')
  })

  it('truncates context over 80 chars with an ellipsis', () => {
    setup()
    const truncated = enriched.context!.slice(0, 80)
    expect(enriched.context!.length).toBeGreaterThan(80)
    expect(screen.getByText(`«${truncated}…»`)).toBeInTheDocument()
  })
})
