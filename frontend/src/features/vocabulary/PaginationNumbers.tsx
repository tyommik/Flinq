import type { JSX } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'

interface Props {
  page: number
  totalPages: number
  onPage: (p: number) => void
}

/**
 * Windowed page list: always includes 1 and totalPages, plus the current
 * page's immediate neighbors. Gaps between kept pages become 'ellipsis'.
 */
function windowedPages(page: number, totalPages: number): (number | 'ellipsis')[] {
  const kept = new Set<number>()
  kept.add(1)
  kept.add(totalPages)
  for (let p = page - 1; p <= page + 1; p++) {
    if (p >= 1 && p <= totalPages) kept.add(p)
  }
  const sorted = Array.from(kept).sort((a, b) => a - b)

  const result: (number | 'ellipsis')[] = []
  let prev: number | null = null
  for (const p of sorted) {
    if (prev !== null && p - prev > 1) result.push('ellipsis')
    result.push(p)
    prev = p
  }
  return result
}

/** Numbered pagination control: ‹ 1 … p-1 p p+1 … N › (spec §3.1). */
export function PaginationNumbers({ page, totalPages, onPage }: Props): JSX.Element {
  const pages = windowedPages(page, totalPages)

  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label="Предыдущая страница"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      {pages.map((p, i) =>
        p === 'ellipsis'
          ? (
            <span key={`ellipsis-${i}`} className="px-1 text-xs text-[var(--vocab-muted-fg)]">
              …
            </span>
            )
          : (
            <button
              key={p}
              type="button"
              aria-label={`Страница ${p}`}
              onClick={() => onPage(p)}
              className={
                p === page
                  ? 'flex h-5 w-5 items-center justify-center rounded-full bg-[var(--vocab-term-fg)] text-xs text-white'
                  : 'text-xs text-[var(--vocab-muted-fg)]'
              }
            >
              {p}
            </button>
            ),
      )}
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label="Следующая страница"
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  )
}
