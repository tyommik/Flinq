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
  const bg = active
    ? 'bg-[var(--reader-tracked-bg)]'
    : s === 'known' || s === 'ignored'
      ? ''
      : 'bg-[var(--reader-new-bg)]'
  return (
    <span
      data-ordinal={token.i}
      role="button"
      tabIndex={-1}
      className={`cursor-pointer rounded-sm px-px hover:brightness-95 ${bg}`}
      onClick={() => onWordClick?.(token)}
    >
      {token.t}
    </span>
  )
})
