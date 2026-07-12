import { isWord, type Sentence, type Token, type WordToken } from '@/api/reader'
import type { PhraseListEntry } from '@/api/vocabulary'

export interface PhraseEntry {
  itemId: string
  words: string[]
  status: 'tracked' | 'known' | 'ignored'
  confidence: number | null
}

/** Первое слово фразы -> кандидаты по убыванию длины (leftmost-longest). */
export type PhraseIndex = Map<string, PhraseEntry[]>

/** Индексируются только tracked-фразы: known/ignored не подсвечиваем (как слова). */
export function buildPhraseIndex(entries: PhraseListEntry[]): PhraseIndex {
  const index: PhraseIndex = new Map()
  for (const e of entries) {
    if (e.status !== 'tracked') continue
    const words = e.phrase_text.split(' ')
    if (words.length < 2) continue
    const firstWord = words[0]
    if (!firstWord) continue
    const list = index.get(firstWord) ?? []
    list.push({ itemId: e.item_id, words, status: e.status, confidence: e.confidence })
    index.set(firstWord, list)
  }
  for (const list of index.values()) list.sort((a, b) => b.words.length - a.words.length)
  return index
}

export interface PhraseMatch {
  /** Индекс в массиве токенов предложения (первый слово-токен фразы). */
  startIdx: number
  /** Индекс последнего слово-токена фразы, включительно. */
  endIdx: number
  entry: PhraseEntry
}

function tryMatch(tokens: Token[], startIdx: number, words: string[]): number | null {
  let wi = 0
  let last = startIdx
  for (let ti = startIdx; ti < tokens.length && wi < words.length; ti++) {
    const tok = tokens[ti]
    if (!tok || !isWord(tok)) continue
    const expectedWord = words[wi]
    if (!expectedWord || tok.n !== expectedWord) return null
    last = ti
    wi++
  }
  return wi === words.length ? last : null
}

/** Пунктуация/пробелы прозрачны; пересечения не поддерживаются. */
export function matchPhrases(tokens: Token[], index: PhraseIndex): PhraseMatch[] {
  const matches: PhraseMatch[] = []
  let i = 0
  while (i < tokens.length) {
    const tok = tokens[i]
    if (!tok || !isWord(tok)) {
      i++
      continue
    }
    const candidates = index.get(tok.n)
    let matched: PhraseMatch | null = null
    if (candidates) {
      for (const entry of candidates) {
        const end = tryMatch(tokens, i, entry.words)
        if (end !== null) {
          matched = { startIdx: i, endIdx: end, entry }
          break
        }
      }
    }
    if (matched) {
      matches.push(matched)
      i = matched.endIdx + 1
    } else {
      i++
    }
  }
  return matches
}

export interface PhraseSelection {
  /** Нормализованный join key (слова через пробел). */
  text: string
  /** Поверхностный срез с пунктуацией, обрезанный по краям. */
  displayText: string
  firstOrdinal: number
}

export function buildSelection(
  sentence: Sentence,
  fromOrdinal: number,
  toOrdinal: number,
): PhraseSelection | null {
  const words = sentence.tokens
    .map((tok, idx) => ({ tok, idx }))
    .filter(
      (x): x is { tok: WordToken; idx: number } =>
        isWord(x.tok) && x.tok.i >= fromOrdinal && x.tok.i <= toOrdinal,
    )
  if (words.length < 2) return null
  const firstWord = words[0]
  const lastWord = words[words.length - 1]
  if (!firstWord || !lastWord) return null
  const startIdx = firstWord.idx
  const endIdx = lastWord.idx
  const displayText = sentence.tokens
    .slice(startIdx, endIdx + 1)
    .map((t) => ('t' in t ? t.t : 'p' in t ? t.p : t.ws))
    .join('')
    .trim()
  const text = words.map((x) => x.tok.n).join(' ')
  return { text, displayText, firstOrdinal: firstWord.tok.i }
}
