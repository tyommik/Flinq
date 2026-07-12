import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Sentence, Token } from '@/api/reader'

import { buildPhraseIndex } from './phraseMatching'
import { SentenceTokens } from './SentenceTokens'

const w = (t: string, i: number): Token => ({ t, n: t.toLowerCase(), i })
const ws: Token = { ws: ' ' }

const sentence: Sentence = {
  seg_id: 's1', index: 0, text: 'so far so good today',
  normalized_text: 'so far so good today',
  tokens: [w('so', 0), ws, w('far', 1), ws, w('so', 2), ws, w('good', 3), ws, w('today', 4)],
}

const index = buildPhraseIndex([
  { item_id: 'ph1', phrase_text: 'so far so good', status: 'tracked', confidence: 1 },
])

describe('SentenceTokens', () => {
  it('wraps a matched phrase and keeps the tail outside', () => {
    render(
      <SentenceTokens
        sentence={sentence} statuses={{}} phraseIndex={index} dragRange={null}
      />,
    )
    const phrase = screen.getByTestId('phrase-span')
    expect(phrase.textContent).toBe('so far so good')
    expect(phrase.textContent).not.toContain('today')
  })

  it('click on the phrase wrapper opens the phrase, not a word', () => {
    const onPhraseClick = vi.fn()
    const onWordClick = vi.fn()
    render(
      <SentenceTokens
        sentence={sentence} statuses={{}} phraseIndex={index} dragRange={null}
        onWordClick={onWordClick} onPhraseClick={onPhraseClick}
      />,
    )
    fireEvent.click(screen.getByTestId('phrase-span'))
    expect(onPhraseClick).toHaveBeenCalledTimes(1)
    expect(onPhraseClick.mock.calls[0]![0].entry.itemId).toBe('ph1')
    expect(onWordClick).not.toHaveBeenCalled()
  })

  it('click on a word inside the phrase opens the word only', () => {
    const onPhraseClick = vi.fn()
    const onWordClick = vi.fn()
    render(
      <SentenceTokens
        sentence={sentence} statuses={{}} phraseIndex={index} dragRange={null}
        onWordClick={onWordClick} onPhraseClick={onPhraseClick}
      />,
    )
    fireEvent.click(screen.getByText('far'))
    expect(onWordClick).toHaveBeenCalledWith({ t: 'far', n: 'far', i: 1 })
    expect(onPhraseClick).not.toHaveBeenCalled()
  })

  it('drag range highlights word tokens', () => {
    render(
      <SentenceTokens
        sentence={sentence} statuses={{}} phraseIndex={new Map()}
        dragRange={{ from: 1, to: 3 }}
      />,
    )
    expect(screen.getByText('far').className).toContain('bg-primary/20')
    expect(screen.getByText('today').className).not.toContain('bg-primary/20')
  })
})
