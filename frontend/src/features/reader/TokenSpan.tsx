import { memo } from 'react'

import type { Token, TokenStatusEntry } from '@/api/reader'

interface Props {
  token: Token
  status?: TokenStatusEntry
  dragSelected?: boolean
  insidePhrase?: boolean
  onWordClick?: (word: { t: string; n: string; i: number }) => void
}

export const TokenSpan = memo(function TokenSpan({
  token,
  status,
  dragSelected,
  insidePhrase,
  onWordClick,
}: Props) {
  if ('ws' in token) return <span>{token.ws}</span>
  if ('p' in token) return <span>{token.p}</span>
  const s = status?.s
  // ADR-0005: tracked — жёлтый фон независимо от confidence (в MVP без градации).
  const active = s === 'tracked'
  // Внутри фразы фон слова не рисуем — фон даёт PhraseSpan; статусная
  // подсветка слова вернётся, как только фраза перестанет матчиться.
  const highlight = insidePhrase
    ? ''
    : active
      ? 'rounded bg-[var(--reader-tracked-bg)] px-1 -mx-1'
      : s === 'known' || s === 'ignored'
        ? ''
        : 'rounded bg-[var(--reader-new-bg)] px-1 -mx-1'
  const drag = dragSelected ? 'rounded bg-primary/20' : ''
  return (
    <span
      data-ordinal={token.i}
      role="button"
      tabIndex={-1}
      className={`cursor-pointer rounded hover:ring-1 hover:ring-foreground/40 ${highlight} ${drag}`}
      onClick={(e) => {
        e.stopPropagation()
        onWordClick?.(token)
      }}
    >
      {token.t}
    </span>
  )
})
