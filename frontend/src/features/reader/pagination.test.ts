import { describe, expect, it } from 'vitest'

import type { Paragraph, PunctToken, Sentence, WhitespaceToken, WordToken } from '@/api/reader'

import { PAGE_SIZE_WORDS, paginate, pageIndexForOrdinal } from './pagination'

/** Builds a sentence with `wordCount` words, assigning globally increasing ordinals. */
function makeSentence(index: number, wordCount: number, nextOrdinal: { value: number }): Sentence {
  const tokens: (WordToken | WhitespaceToken | PunctToken)[] = []
  for (let w = 0; w < wordCount; w += 1) {
    if (w > 0) tokens.push({ ws: ' ' })
    const ordinal = nextOrdinal.value
    tokens.push({ t: `word${ordinal}`, n: `word${ordinal}`, i: ordinal })
    nextOrdinal.value += 1
  }
  tokens.push({ p: '.' })
  return {
    seg_id: `seg-${index}`,
    index,
    text: `sentence ${index}`,
    normalized_text: `sentence ${index}`,
    tokens,
  }
}

/** Builds a single paragraph containing one sentence per entry in `wordCounts`. */
function makeParagraphs(wordCounts: number[]): Paragraph[] {
  const nextOrdinal = { value: 0 }
  return [{ sentences: wordCounts.map((wc, i) => makeSentence(i, wc, nextOrdinal)) }]
}

describe('paginate', () => {
  it('returns no pages for empty content', () => {
    expect(paginate([])).toEqual([])
  })

  it('splits evenly-worded sentences into sentence-aligned pages of >= 250 words each', () => {
    // 100 sentences of 6 words = 600 words total, several pages expected.
    const counts = Array.from({ length: 100 }, () => 6)
    const paragraphs = makeParagraphs(counts)
    const pages = paginate(paragraphs)

    expect(pages.length).toBeGreaterThan(1)

    // Every sentence appears exactly once, in original order, across all pages
    // (i.e. page boundaries never split a sentence).
    const allSentenceIndexes = pages.flatMap((p) => p.sentences.map((s) => s.sentence.index))
    expect(allSentenceIndexes).toEqual(Array.from({ length: 100 }, (_, i) => i))

    // Every page but the last must have reached the page-size threshold.
    for (const page of pages.slice(0, -1)) {
      expect(page.wordCount).toBeGreaterThanOrEqual(PAGE_SIZE_WORDS)
    }
    const last = pages[pages.length - 1]!
    expect(last.sentences.length).toBeGreaterThan(0)

    const totalWords = pages.reduce((sum, p) => sum + p.wordCount, 0)
    expect(totalWords).toBe(600)
  })

  it('keeps a single oversized sentence on one page instead of splitting it', () => {
    const paragraphs = makeParagraphs([900])
    const pages = paginate(paragraphs)

    expect(pages).toHaveLength(1)
    expect(pages[0]!.sentences).toHaveLength(1)
    expect(pages[0]!.wordCount).toBe(900)
    expect(pages[0]!.fromOrdinal).toBe(0)
    expect(pages[0]!.toOrdinal).toBe(899)
  })

  it('produces ordinal ranges that are non-overlapping and strictly ascending across pages', () => {
    const counts = Array.from({ length: 100 }, () => 6)
    const paragraphs = makeParagraphs(counts)
    const pages = paginate(paragraphs)

    for (const page of pages) {
      expect(page.fromOrdinal).toBeLessThanOrEqual(page.toOrdinal)
    }
    for (let i = 1; i < pages.length; i += 1) {
      expect(pages[i]!.fromOrdinal).toBeGreaterThan(pages[i - 1]!.toOrdinal)
    }
  })

  it('tracks the originating paragraph index across multiple paragraphs', () => {
    const nextOrdinal = { value: 0 }
    const paragraphs: Paragraph[] = [
      { sentences: [makeSentence(0, 3, nextOrdinal)] },
      { sentences: [makeSentence(1, 3, nextOrdinal), makeSentence(2, 3, nextOrdinal)] },
    ]
    const pages = paginate(paragraphs, 100)

    expect(pages).toHaveLength(1)
    expect(pages[0]!.sentences.map((s) => s.paragraphIndex)).toEqual([0, 1, 1])
  })

  it('merges a trailing punctuation-only sentence into the last page instead of flushing it alone', () => {
    // Enough word sentences to close a page at pageSize=100, followed by a
    // trailing word-free sentence (e.g. a lone closing quote/ellipsis line).
    const counts = [100, 0]
    const paragraphs = makeParagraphs(counts)
    const pages = paginate(paragraphs, 100)

    expect(pages).toHaveLength(1)
    expect(pages[0]!.sentences.map((s) => s.sentence.index)).toEqual([0, 1])
    expect(pages[0]!.wordCount).toBe(100)
    for (const page of pages) {
      expect(page.fromOrdinal).not.toBe(Infinity)
    }
  })

  it('emits a single explicit empty page when the entire input has zero word tokens', () => {
    const counts = [0, 0, 0]
    const paragraphs = makeParagraphs(counts)
    const pages = paginate(paragraphs, 100)

    expect(pages).toHaveLength(1)
    expect(pages[0]!.wordCount).toBe(0)
    expect(pages[0]!.fromOrdinal).toBe(0)
    expect(pages[0]!.toOrdinal).toBe(-1)
    expect(pageIndexForOrdinal(pages, 5)).toBe(0)
  })

  it('invariant sweep: every page has finite ordinals with fromOrdinal <= toOrdinal, or is explicitly empty', () => {
    const counts = [50, 60, 70, 80, 0, 0, 90]
    const paragraphs = makeParagraphs(counts)
    const pages = paginate(paragraphs, 100)

    for (const page of pages) {
      const invariant =
        (Number.isFinite(page.fromOrdinal) && page.fromOrdinal <= page.toOrdinal) || page.wordCount === 0
      expect(invariant).toBe(true)
    }
  })
})

describe('pageIndexForOrdinal', () => {
  const counts = Array.from({ length: 100 }, () => 6)
  const paragraphs = makeParagraphs(counts)
  const pages = paginate(paragraphs)

  it('returns 0 when ordinal is null', () => {
    expect(pageIndexForOrdinal(pages, null)).toBe(0)
  })

  it('finds the page whose ordinal range contains the given ordinal', () => {
    const secondPage = pages[1]!
    expect(pageIndexForOrdinal(pages, secondPage.fromOrdinal)).toBe(1)
    expect(pageIndexForOrdinal(pages, secondPage.toOrdinal)).toBe(1)
  })

  it('falls back to 0 when the ordinal is out of range', () => {
    const outOfRange = pages[pages.length - 1]!.toOrdinal + 1000
    expect(pageIndexForOrdinal(pages, outOfRange)).toBe(0)
  })
})
