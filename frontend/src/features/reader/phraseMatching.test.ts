import { describe, expect, it } from 'vitest'

import type { Token } from '@/api/reader'
import type { PhraseListEntry } from '@/api/vocabulary'

import { buildPhraseIndex, buildSelection, matchPhrases } from './phraseMatching'

const ws: Token = { ws: ' ' }
const w = (t: string, i: number, n = t.toLowerCase()): Token => ({ t, n, i })
const p = (s: string): Token => ({ p: s })

const entry = (
  id: string,
  phrase_text: string,
  status: PhraseListEntry['status'] = 'tracked',
): PhraseListEntry => ({ item_id: id, phrase_text, status, confidence: 1 })

// "So far , so good it is"
const tokens: Token[] = [
  w('So', 10), ws, w('far', 11), p(','), ws, w('so', 12), ws, w('good', 13),
  ws, w('it', 14), ws, w('is', 15),
]

describe('buildPhraseIndex', () => {
  it('indexes tracked phrases by first word, longest first', () => {
    const idx = buildPhraseIndex([entry('a', 'so far'), entry('b', 'so far so good')])
    const list = idx.get('so')
    expect(list).toBeDefined()
    if (list) {
      expect(list.map((e) => e.itemId)).toEqual(['b', 'a'])
    }
  })

  it('skips known/ignored phrases', () => {
    const idx = buildPhraseIndex([entry('a', 'so far', 'known')])
    expect(idx.size).toBe(0)
  })
})

describe('matchPhrases', () => {
  it('matches across punctuation (leftmost-longest)', () => {
    const idx = buildPhraseIndex([entry('a', 'so far'), entry('b', 'so far so good')])
    const matches = matchPhrases(tokens, idx)
    expect(matches).toHaveLength(1)
    const match = matches[0]
    if (match) {
      expect(match).toMatchObject({ startIdx: 0, endIdx: 7 })
      expect(match.entry.itemId).toBe('b')
    }
  })

  it('non-overlapping: next scan starts after previous match', () => {
    const idx = buildPhraseIndex([entry('a', 'so good'), entry('b', 'good it')])
    const matches = matchPhrases(tokens, idx)
    expect(matches).toHaveLength(1)
    const match = matches[0]
    if (match) {
      expect(match.entry.itemId).toBe('a')
    }
  })

  it('no match when a word differs', () => {
    const idx = buildPhraseIndex([entry('a', 'so bad')])
    expect(matchPhrases(tokens, idx)).toHaveLength(0)
  })

  it("matches phrases containing don't as one word", () => {
    const toks: Token[] = [w("Don't", 0, "don't"), ws, w('stop', 1)]
    const idx = buildPhraseIndex([entry('a', "don't stop")])
    expect(matchPhrases(toks, idx)).toHaveLength(1)
  })
})

describe('buildSelection', () => {
  const sentence = {
    seg_id: 's1', index: 0, text: 'So far, so good it is',
    normalized_text: 'so far so good it is', tokens,
  }

  it('builds normalized and display text over the ordinal range', () => {
    const sel = buildSelection(sentence, 10, 13)
    expect(sel).toEqual({
      text: 'so far so good',
      displayText: 'So far, so good',
      firstOrdinal: 10,
    })
  })

  it('returns null for a single word', () => {
    expect(buildSelection(sentence, 12, 12)).toBeNull()
  })

  it('returns null when range has no words', () => {
    expect(buildSelection(sentence, 90, 99)).toBeNull()
  })
})
