import { useState } from 'react'

import { ApiError } from '@/api/client'
import { isWord, type Sentence, type StatusMap, type WordToken } from '@/api/reader'

import { TokenSpan } from './TokenSpan'
import { useSegmentTranslation } from './useReaderQueries'

// TODO(FLQ-9): read from user settings
export const DEFAULT_TRANSLATION_LANG = 'ru' as const

interface SelectedWord {
  t: string
  n: string
  i: number
}

interface Props {
  lessonId: string
  sentence: Sentence
  statuses: StatusMap
  targetLang: 'en' | 'ru' | 'pt'
  onWordClick?: (word: SelectedWord) => void
  onPrev: () => void
  onNext: () => void
  canPrev: boolean
  canNext: boolean
}

function translationErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 503) {
    return 'AI отключён администратором'
  }
  return 'Не удалось перевести'
}

function collectTrackedWords(sentence: Sentence, statuses: StatusMap): WordToken[] {
  const seen = new Set<string>()
  const tracked: WordToken[] = []
  for (const token of sentence.tokens) {
    if (!isWord(token)) continue
    if (statuses[token.n]?.s !== 'tracked') continue
    if (seen.has(token.n)) continue
    seen.add(token.n)
    tracked.push(token)
  }
  return tracked
}

export function SentenceView({
  lessonId,
  sentence,
  statuses,
  targetLang,
  onWordClick,
  onPrev,
  onNext,
  canPrev,
  canNext,
}: Props) {
  const [expanded, setExpanded] = useState(false)
  const [translationRequested, setTranslationRequested] = useState(false)

  const translation = useSegmentTranslation(
    lessonId,
    sentence.seg_id,
    targetLang,
    translationRequested,
  )

  const handleToggle = () => {
    if (!translationRequested) setTranslationRequested(true)
    setExpanded((e) => !e)
  }

  const trackedWords = collectTrackedWords(sentence, statuses)

  const showRetry =
    translation.isError && !(translation.error instanceof ApiError && translation.error.status === 503)

  return (
    <div className="mx-auto max-w-[720px] text-2xl">
      <div className="flex items-center justify-center gap-4">
        <button
          type="button"
          onClick={onPrev}
          disabled={!canPrev}
          aria-label="‹"
          className="rounded-md px-2 py-1 text-lg hover:bg-accent disabled:pointer-events-none disabled:opacity-50"
        >
          ‹
        </button>
        <p className="text-center">
          {sentence.tokens.map((token, i) => (
            <TokenSpan
              key={i}
              token={token}
              status={isWord(token) ? statuses[token.n] : undefined}
              onWordClick={onWordClick}
            />
          ))}
        </p>
        <button
          type="button"
          onClick={onNext}
          disabled={!canNext}
          aria-label="›"
          className="rounded-md px-2 py-1 text-lg hover:bg-accent disabled:pointer-events-none disabled:opacity-50"
        >
          ›
        </button>
      </div>

      <div className="mt-4 flex justify-center">
        <button
          type="button"
          data-testid="toggle-translation"
          onClick={handleToggle}
          className="text-sm font-medium text-primary hover:underline"
        >
          Показать перевод ▾
        </button>
      </div>

      {expanded && (
        <div data-testid="sentence-translation" className="mt-2 text-center text-base">
          {translation.isLoading && <p className="text-muted-foreground">Переводим…</p>}
          {translation.isError && (
            <div>
              <p className="text-destructive">{translationErrorMessage(translation.error)}</p>
              {showRetry && (
                <button
                  type="button"
                  onClick={() => translation.refetch()}
                  className="mt-1 text-sm underline"
                >
                  Повторить
                </button>
              )}
            </div>
          )}
          {translation.isSuccess && (
            <p>
              {translation.data.text}
              {translation.data.source === 'ai' && (
                <span className="ml-2 inline-block rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
                  AI
                </span>
              )}
            </p>
          )}
        </div>
      )}

      {trackedWords.length > 0 && (
        <div data-testid="sentence-vocab" className="mt-6 flex flex-wrap justify-center gap-3">
          {trackedWords.map((token) => (
            <button
              key={token.n}
              type="button"
              onClick={() => onWordClick?.(token)}
              className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--reader-tracked-bg)] text-xs">
                {statuses[token.n]?.c ?? 0}
              </span>
              <span>{token.t}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
