import { useState } from 'react'
import { Play } from 'lucide-react'

import { ApiError } from '@/api/client'
import { isWord, type Sentence, type StatusMap, type WordToken } from '@/api/reader'

import type { PhraseIndex, PhraseMatch } from './phraseMatching'
import { SentenceTokens } from './SentenceTokens'
import { SentenceVocabList } from './SentenceVocabList'
import { useSegmentTranslation } from './useReaderQueries'
import type { DragRange } from './usePhraseSelection'

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
  phraseIndex: PhraseIndex
  dragRange: DragRange | null
  lang: string
  targetLang: 'en' | 'ru' | 'pt'
  onWordClick?: (word: SelectedWord) => void
  onPhraseClick?: (match: PhraseMatch, sentence: Sentence) => void
}

function translationErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 503) {
    return 'AI отключён администратором'
  }
  return 'Не удалось перевести'
}

// Слова для списка лексики: изучаемые (tracked) и новые (без статуса).
// known/ignored не показываем. Дедупликация по нормализованной форме.
function collectVocabWords(sentence: Sentence, statuses: StatusMap): WordToken[] {
  const seen = new Set<string>()
  const words: WordToken[] = []
  for (const token of sentence.tokens) {
    if (!isWord(token)) continue
    const s = statuses[token.n]?.s
    if (s === 'known' || s === 'ignored') continue
    if (seen.has(token.n)) continue
    seen.add(token.n)
    words.push(token)
  }
  return words
}

export function SentenceView({
  lessonId,
  sentence,
  statuses,
  phraseIndex,
  dragRange,
  lang,
  targetLang,
  onWordClick,
  onPhraseClick,
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

  const vocabWords = collectVocabWords(sentence, statuses)

  const showRetry =
    translation.isError && !(translation.error instanceof ApiError && translation.error.status === 503)

  return (
    <div className="mx-auto max-w-[900px]">
      <div className="flex justify-center">
        <button
          type="button"
          disabled
          title="Скоро"
          aria-label="Воспроизвести аудио"
          className="flex h-[54px] w-[54px] items-center justify-center rounded-full border-[1.5px] border-[#D9DBE0] disabled:opacity-60"
        >
          <Play aria-hidden className="h-5 w-5" />
        </button>
      </div>

      <div className="mt-10 px-4 sm:px-16">
        <p className="text-xl leading-[1.8]">
          <SentenceTokens
            sentence={sentence}
            statuses={statuses}
            phraseIndex={phraseIndex}
            dragRange={dragRange}
            onWordClick={onWordClick}
            onPhraseClick={onPhraseClick}
          />
        </p>

        <div className="mt-4">
          <button
            type="button"
            data-testid="toggle-translation"
            onClick={handleToggle}
            className="text-sm text-muted-foreground underline hover:text-foreground"
          >
            Показать перевод ▾
          </button>
        </div>

        {expanded && (
          <div data-testid="sentence-translation" className="mt-2 text-sm italic">
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
                  <span className="ml-2 inline-block rounded-full bg-muted px-2 py-0.5 text-xs font-medium not-italic">
                    AI
                  </span>
                )}
              </p>
            )}
          </div>
        )}

        <div className="mt-8">
          <SentenceVocabList
            words={vocabWords}
            statuses={statuses}
            lang={lang}
            target={targetLang}
            onWordClick={onWordClick}
          />
        </div>
      </div>
    </div>
  )
}
