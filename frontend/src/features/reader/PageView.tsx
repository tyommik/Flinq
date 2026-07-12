import { Fragment } from 'react'

import type { Sentence, StatusMap } from '@/api/reader'

import type { PageSlice } from './pagination'
import type { PhraseIndex, PhraseMatch } from './phraseMatching'
import { SentenceTokens } from './SentenceTokens'
import type { DragRange } from './usePhraseSelection'

interface Props {
  page: PageSlice
  statuses: StatusMap
  phraseIndex: PhraseIndex
  dragRange: DragRange | null
  onWordClick?: (word: { t: string; n: string; i: number }) => void
  onPhraseClick?: (match: PhraseMatch, sentence: Sentence) => void
}

export function PageView({ page, statuses, phraseIndex, dragRange, onWordClick, onPhraseClick }: Props) {
  const paragraphOrder: number[] = []
  const paragraphs = new Map<number, PageSlice['sentences']>()
  for (const entry of page.sentences) {
    if (!paragraphs.has(entry.paragraphIndex)) {
      paragraphs.set(entry.paragraphIndex, [])
      paragraphOrder.push(entry.paragraphIndex)
    }
    paragraphs.get(entry.paragraphIndex)!.push(entry)
  }

  return (
    <div className="mx-auto max-w-[720px]">
      <div>
        {paragraphOrder.map((paragraphIndex) => (
          <p key={paragraphIndex} className="mb-4">
            {paragraphs.get(paragraphIndex)!.map((entry, sentenceIdx) => (
              <Fragment key={entry.sentence.seg_id}>
                {sentenceIdx > 0 && ' '}
                <SentenceTokens
                  sentence={entry.sentence}
                  statuses={statuses}
                  phraseIndex={phraseIndex}
                  dragRange={dragRange}
                  onWordClick={onWordClick}
                  onPhraseClick={onPhraseClick}
                />
              </Fragment>
            ))}
          </p>
        ))}
      </div>
    </div>
  )
}
