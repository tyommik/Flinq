import type { VocabListItem } from '@/api/vocabulary'
import { ConfidencePicker } from '@/components/ConfidencePicker'

const CONTEXT_MAX = 80

interface Props {
  items: VocabListItem[]
  selection: string[]
  onToggleSelected: (id: string) => void
  onSelectPage: (ids: string[]) => void
  onClearSelection: () => void
  onPick: (itemId: string, status: 'tracked' | 'known' | 'ignored', confidence: number | null) => void
  onOpenTerm: (item: VocabListItem) => void
}

function truncateContext(context: string): string {
  return context.length > CONTEXT_MAX ? `${context.slice(0, CONTEXT_MAX)}…` : context
}

/** Mobile (<md) vocabulary card list — same contract as VocabularyTable. */
export function VocabularyCardList({
  items,
  selection,
  onToggleSelected,
  onPick,
  onOpenTerm,
}: Props) {
  return (
    <div data-testid="vocab-card-list" className="space-y-3 md:hidden">
      {items.map((item) => (
        <div
          key={item.item_id}
          data-testid="vocab-card"
          className="relative rounded-lg border border-[var(--vocab-card-border)] bg-white p-4"
        >
          <input
            type="checkbox"
            aria-label={`Выбрать ${item.text}`}
            checked={selection.includes(item.item_id)}
            onChange={() => onToggleSelected(item.item_id)}
            className="absolute right-3 top-3"
          />
          <div className="flex items-start justify-between gap-3 pr-8">
            <button
              type="button"
              onClick={() => onOpenTerm(item)}
              className="text-left text-[15px] font-semibold text-[var(--vocab-term-fg)] hover:underline"
            >
              {item.text}
            </button>
            <span className="text-right text-sm text-[var(--vocab-translation-fg)]">
              {item.primary_translation !== null
                ? item.primary_translation.text
                : <span className="text-[var(--vocab-muted-fg)]">—</span>}
            </span>
          </div>
          {(item.pos !== null || item.tags.length > 0) && (
            <div className="mt-1 flex flex-wrap gap-1">
              {item.pos !== null && (
                <span className="h-5 rounded px-1.5 text-[11px] leading-5 bg-[var(--vocab-chip-pos-bg)]">
                  {item.pos}
                </span>
              )}
              {item.tags.map((tag) => (
                <span
                  key={tag}
                  className="h-5 rounded px-1.5 text-[11px] leading-5 bg-[var(--vocab-chip-gram-bg)]"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
          {item.context !== null && (
            <p className="mt-2 text-[13px] italic text-[var(--vocab-muted-fg)]">
              «{truncateContext(item.context)}»
            </p>
          )}
          <div className="mt-3 border-t border-border pt-2">
            <ConfidencePicker
              status={item.status}
              confidence={item.confidence}
              onSelect={(status, confidence) => onPick(item.item_id, status, confidence)}
              size="sm"
            />
          </div>
        </div>
      ))}
    </div>
  )
}
