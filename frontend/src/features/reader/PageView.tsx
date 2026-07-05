import { Fragment } from 'react'

import { isWord, type StatusMap } from '@/api/reader'

import type { PageSlice } from './pagination'
import { TokenSpan } from './TokenSpan'

interface Props {
  page: PageSlice
  statuses: StatusMap
  onWordClick?: (word: { t: string; n: string; i: number }) => void
  onPrev: () => void
  onNext: () => void
  canPrev: boolean
  canNext: boolean
}

export function PageView({ page, statuses, onWordClick, onPrev, onNext, canPrev, canNext }: Props) {
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
                {entry.sentence.tokens.map((token, tokenIdx) => (
                  <TokenSpan
                    key={tokenIdx}
                    token={token}
                    status={isWord(token) ? statuses[token.n] : undefined}
                    onWordClick={onWordClick}
                  />
                ))}
              </Fragment>
            ))}
          </p>
        ))}
      </div>

      <div className="flex items-center justify-between py-6">
        <button
          type="button"
          onClick={onPrev}
          disabled={!canPrev}
          className="rounded-md px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:pointer-events-none disabled:opacity-50"
        >
          Назад
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!canNext}
          className="rounded-md px-3 py-1.5 text-sm font-medium hover:bg-accent disabled:pointer-events-none disabled:opacity-50"
        >
          Далее
        </button>
      </div>
    </div>
  )
}
