import { useEffect } from 'react'
import { X } from 'lucide-react'

import type { TokenStatusEntry } from '@/api/reader'

interface SelectedWord {
  t: string
  n: string
  i: number
}

interface Props {
  word: SelectedWord | null
  status?: TokenStatusEntry
  onClose: () => void
}

function statusBadge(status?: TokenStatusEntry): string {
  if (!status) return 'new'
  if (status.s === 'tracked') return `tracked ${status.c ?? 0}`
  return status.s
}

export function WordCardPlaceholder({ word, status, onClose }: Props) {
  useEffect(() => {
    if (!word) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [word, onClose])

  if (!word) return null

  return (
    <>
      <div
        data-testid="word-card-backdrop"
        className="fixed inset-0 z-[var(--z-modal-backdrop)] bg-black/10 md:hidden"
        onClick={onClose}
      />
      <div
        data-testid="word-card-placeholder"
        className="fixed inset-x-0 bottom-0 z-[var(--z-modal)] rounded-t-xl border border-border bg-card p-4 shadow-lg md:inset-x-auto md:right-0 md:top-0 md:h-full md:w-80 md:rounded-none md:border-y-0 md:border-r-0 md:border-l md:shadow-none"
      >
        <button
          type="button"
          aria-label="Закрыть"
          onClick={onClose}
          className="absolute right-3 top-3 rounded-md p-1 hover:bg-accent"
        >
          <X className="h-4 w-4" />
        </button>

        <p className="text-2xl font-semibold">{word.t}</p>
        <p className="text-sm text-muted-foreground">{word.n}</p>
        <span
          data-testid="word-card-status"
          className="mt-2 inline-block rounded-full bg-muted px-2 py-0.5 text-xs font-medium"
        >
          {statusBadge(status)}
        </span>
        <p className="mt-4 text-sm text-muted-foreground">Карточка слова появится в FLQ-5</p>
      </div>
    </>
  )
}
