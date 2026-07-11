import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { VocabListItem } from '@/api/vocabulary'
import { VocabularyCardList } from './VocabularyCardList'

const enriched: VocabListItem = {
  item_id: 'i1',
  kind: 'token',
  text: 'abaixaram',
  status: 'tracked',
  confidence: 2,
  primary_translation: { text: 'опустили', target_language_code: 'ru' },
  tags: ['verbs'],
  pos: 'verb',
  context: 'Sacerdotes e fiéis abaixaram a cabeça diante do altar.',
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
    <VocabularyCardList
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

describe('VocabularyCardList', () => {
  it('renders one card per item with term, translation, chips and context', () => {
    setup()
    const cards = screen.getAllByTestId('vocab-card')
    expect(cards).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'abaixaram' })).toBeInTheDocument()
    expect(screen.getByText('опустили')).toBeInTheDocument()
    expect(screen.getByText('verbs')).toBeInTheDocument()
    expect(screen.getByText('verb')).toBeInTheDocument()
    expect(screen.getByText(/«Sacerdotes e fiéis/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'casa' })).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('fires onOpenTerm with the item when the term is clicked', () => {
    const { onOpenTerm } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'abaixaram' }))
    expect(onOpenTerm).toHaveBeenCalledWith(enriched)
  })

  it('the footer ConfidencePicker fires onPick(id, "tracked", 3)', () => {
    const { onPick } = setup()
    const levelThreeButtons = screen.getAllByRole('button', { name: 'Уровень 3' })
    fireEvent.click(levelThreeButtons[0]!)
    expect(onPick).toHaveBeenCalledWith('i1', 'tracked', 3)
  })

  it('the selection checkbox fires onToggleSelected(id)', () => {
    const { onToggleSelected } = setup()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать abaixaram' }))
    expect(onToggleSelected).toHaveBeenCalledWith('i1')
  })
})
