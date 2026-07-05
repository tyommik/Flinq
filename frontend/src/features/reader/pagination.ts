import { isWord, type Paragraph, type Sentence } from '@/api/reader'

export interface PageSlice {
  sentences: { paragraphIndex: number; sentence: Sentence }[]
  fromOrdinal: number
  toOrdinal: number
  wordCount: number
}

export const PAGE_SIZE_WORDS = 250

export function paginate(paragraphs: Paragraph[], pageSize: number = PAGE_SIZE_WORDS): PageSlice[] {
  const flat = paragraphs.flatMap((p, paragraphIndex) =>
    p.sentences.map((sentence) => ({ paragraphIndex, sentence })),
  )
  const pages: PageSlice[] = []
  let current: PageSlice | null = null
  for (const entry of flat) {
    const words = entry.sentence.tokens.filter(isWord)
    if (!current) current = { sentences: [], fromOrdinal: Infinity, toOrdinal: -1, wordCount: 0 }
    current.sentences.push(entry)
    if (words.length > 0) {
      current.fromOrdinal = Math.min(current.fromOrdinal, words[0]!.i)
      current.toOrdinal = Math.max(current.toOrdinal, words[words.length - 1]!.i)
      current.wordCount += words.length
    }
    if (current.wordCount >= pageSize) {
      pages.push(current)
      current = null
    }
  }
  if (current && current.sentences.length > 0) {
    if (current.wordCount === 0 && pages.length > 0) {
      // Trailing run of word-free sentences (e.g. a punctuation-only closing
      // line) has no ordinals of its own — fold it into the last page rather
      // than flushing a degenerate fromOrdinal=Infinity/toOrdinal=-1 page.
      pages[pages.length - 1]!.sentences.push(...current.sentences)
    } else if (current.wordCount === 0) {
      // The entire input contained zero word tokens. There is no preceding
      // page to merge into, so emit a single explicit empty page — empty
      // page — callers must skip bulk-known when wordCount === 0.
      pages.push({ ...current, fromOrdinal: 0, toOrdinal: -1 })
    } else {
      pages.push(current)
    }
  }
  return pages
}

export function pageIndexForOrdinal(pages: PageSlice[], ordinal: number | null): number {
  if (ordinal == null) return 0
  const idx = pages.findIndex((p) => ordinal >= p.fromOrdinal && ordinal <= p.toOrdinal)
  return idx === -1 ? 0 : idx
}
