import { useQueries } from '@tanstack/react-query'
import { Volume2 } from 'lucide-react'

import type { StatusMap, WordToken } from '@/api/reader'
import { vocabularyApi } from '@/api/vocabulary'
import { cn } from '@/lib/utils'

import { wordLookupKey } from './useWordCard'

interface Props {
  words: WordToken[]
  statuses: StatusMap
  lang: string
  target: string
  onWordClick?: (word: WordToken) => void
}

export function SentenceVocabList({ words, statuses, lang, target, onWordClick }: Props) {
  // Тот же query key, что у WordCard (lookup по нормализованной форме) —
  // открытие карточки и список делят кэш и не дублируют запросы.
  const lookups = useQueries({
    queries: words.map((w) => ({
      queryKey: wordLookupKey('token', lang, w.n, target),
      queryFn: () => vocabularyApi.lookup(lang, w.n, target, 'token'),
    })),
  })

  if (words.length === 0) return null

  return (
    <ul data-testid="sentence-vocab">
      {words.map((w, idx) => {
        const tracked = statuses[w.n]?.s === 'tracked'
        const translation = lookups[idx]?.data?.translations.primary?.text ?? null
        return (
          <li key={w.i}>
            <button
              type="button"
              onClick={() => onWordClick?.(w)}
              className="flex w-full items-center gap-4 rounded-md py-3 text-left hover:bg-accent/50"
            >
              <span
                className={cn(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold text-[var(--reader-status-foreground)]',
                  tracked
                    ? 'bg-[var(--reader-status-tracked-bg)]'
                    : 'bg-[var(--reader-new-bg)]',
                )}
              >
                {tracked ? (statuses[w.n]?.c ?? 0) : '•'}
              </span>
              <span className="min-w-0">
                <span className="flex items-center gap-2">
                  <span className="text-base font-medium">{w.t}</span>
                  <Volume2
                    aria-hidden
                    className="h-3.5 w-3.5 text-muted-foreground opacity-60"
                  />
                </span>
                {translation && (
                  <span className="mt-0.5 block text-sm text-muted-foreground">
                    {translation}
                  </span>
                )}
              </span>
            </button>
            {idx < words.length - 1 && (
              <div aria-hidden className="ml-11 border-b border-border" />
            )}
          </li>
        )
      })}
    </ul>
  )
}
