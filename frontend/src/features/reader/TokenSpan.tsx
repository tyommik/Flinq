import { memo } from 'react'
import type { Token, TokenStatusEntry } from '@/api/reader'

interface Props {
  token: Token
  status?: TokenStatusEntry
  onWordClick?: (word: { t: string; n: string; i: number }) => void
}

export const TokenSpan = memo(function TokenSpan({ token, status, onWordClick }: Props) {
  if ('ws' in token) return <span>{token.ws}</span>
  if ('p' in token) return <span>{token.p}</span>
  const s = status?.s
  const active = s === 'tracked' && (status?.c ?? 0) >= 1
  const highlight = active
    ? 'rounded bg-[var(--reader-tracked-bg)] px-1 -mx-1'
    : s === 'known' || s === 'ignored'
      ? ''
      : 'rounded bg-[var(--reader-new-bg)] px-1 -mx-1'
  return (
    <span
      data-ordinal={token.i}
      role="button"
      tabIndex={-1}
      className={`cursor-pointer hover:brightness-95 ${highlight}`}
      onClick={() => onWordClick?.(token)}
    >
      {token.t}
    </span>
  )
})
