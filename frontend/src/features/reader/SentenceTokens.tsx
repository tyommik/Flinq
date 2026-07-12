import { useMemo, type ReactNode } from 'react'

import { isWord, type Sentence, type StatusMap } from '@/api/reader'

import { matchPhrases, type PhraseIndex, type PhraseMatch } from './phraseMatching'
import { PhraseSpan } from './PhraseSpan'
import { TokenSpan } from './TokenSpan'
import type { DragRange } from './usePhraseSelection'

interface Props {
  sentence: Sentence
  statuses: StatusMap
  phraseIndex: PhraseIndex
  dragRange: DragRange | null
  onWordClick?: (word: { t: string; n: string; i: number }) => void
  onPhraseClick?: (match: PhraseMatch, sentence: Sentence) => void
}

export function SentenceTokens({
  sentence,
  statuses,
  phraseIndex,
  dragRange,
  onWordClick,
  onPhraseClick,
}: Props) {
  const matches = useMemo(
    () => matchPhrases(sentence.tokens, phraseIndex),
    [sentence, phraseIndex],
  )
  const matchByStart = useMemo(
    () => new Map(matches.map((m) => [m.startIdx, m])),
    [matches],
  )

  const inDrag = (tokIdx: number): boolean => {
    if (!dragRange) return false
    const tok = sentence.tokens[tokIdx]
    return !!tok && isWord(tok) && tok.i >= dragRange.from && tok.i <= dragRange.to
  }

  const nodes: ReactNode[] = []
  for (let idx = 0; idx < sentence.tokens.length; idx++) {
    const match = matchByStart.get(idx)
    if (match) {
      const { startIdx, endIdx } = match
      nodes.push(
        <PhraseSpan key={`ph-${startIdx}`} onClick={() => onPhraseClick?.(match, sentence)}>
          {sentence.tokens.slice(startIdx, endIdx + 1).map((token, j) => (
            <TokenSpan
              key={startIdx + j}
              token={token}
              status={isWord(token) ? statuses[token.n] : undefined}
              dragSelected={inDrag(startIdx + j)}
              insidePhrase
              onWordClick={onWordClick}
            />
          ))}
        </PhraseSpan>,
      )
      idx = endIdx
      continue
    }
    const token = sentence.tokens[idx]
    if (!token) continue
    nodes.push(
      <TokenSpan
        key={idx}
        token={token}
        status={isWord(token) ? statuses[token.n] : undefined}
        dragSelected={inDrag(idx)}
        onWordClick={onWordClick}
      />,
    )
  }
  return <>{nodes}</>
}
