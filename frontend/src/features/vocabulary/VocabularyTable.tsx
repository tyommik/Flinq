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

const GRID_COLS =
  'grid-cols-[40px_minmax(240px,1fr)_minmax(200px,0.8fr)_minmax(240px,1fr)_260px]'

const FLAGS: Record<string, string> = {
  ru: '🇷🇺',
  en: '🇬🇧',
  pt: '🇧🇷',
}

/** Flag emoji for a target language code (spec §2.2); unknown codes fall back to a neutral flag. */
function flagFor(code: string): string {
  return FLAGS[code] ?? '🏳'
}

function truncateContext(context: string): string {
  return context.length > CONTEXT_MAX ? `${context.slice(0, CONTEXT_MAX)}…` : context
}

/** Desktop (≥md) vocabulary card-row list: checkbox / term+chips / translation / source text / picker. */
export function VocabularyTable({
  items,
  selection,
  onToggleSelected,
  onSelectPage,
  onClearSelection,
  onPick,
  onOpenTerm,
}: Props) {
  const pageIds = items.map((item) => item.item_id)
  const allSelected = pageIds.length > 0 && pageIds.every((id) => selection.includes(id))

  return (
    <div className="hidden md:block">
      <div className={`grid ${GRID_COLS} items-center px-4 py-2`}>
        <input
          type="checkbox"
          aria-label="Выбрать все на странице"
          checked={allSelected}
          onChange={() => (allSelected ? onClearSelection() : onSelectPage(pageIds))}
        />
        <span className="text-[11px] font-semibold uppercase tracking-[0.5px] text-[var(--vocab-header-fg)]">
          ТЕРМИН
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-[0.5px] text-[var(--vocab-header-fg)]">
          ПЕРЕВОД
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-[0.5px] text-[var(--vocab-header-fg)]">
          ИСХОДНЫЙ ТЕКСТ
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-[0.5px] text-[var(--vocab-header-fg)]">
          СТАТУС
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <div
            key={item.item_id}
            className={`grid ${GRID_COLS} items-center rounded-lg border border-[var(--vocab-card-border)] bg-white px-4 py-3`}
          >
            <input
              type="checkbox"
              aria-label={`Выбрать ${item.text}`}
              checked={selection.includes(item.item_id)}
              onChange={() => onToggleSelected(item.item_id)}
            />
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={() => onOpenTerm(item)}
                className="text-left text-[15px] font-semibold text-[var(--vocab-term-fg)] hover:underline"
              >
                {item.text}
              </button>
              {(item.pos !== null || item.tags.length > 0) && (
                <div className="flex flex-wrap gap-1">
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
            </div>
            <div>
              {item.primary_translation !== null
                ? (
                  <span className="flex items-center gap-1.5 text-[var(--vocab-translation-fg)]">
                    <span aria-hidden="true">{flagFor(item.primary_translation.target_language_code)}</span>
                    <span>{item.primary_translation.text}</span>
                  </span>
                  )
                : <span className="text-[var(--vocab-muted-fg)]">—</span>}
            </div>
            <div>
              {item.context !== null
                ? (
                  <span className="line-clamp-2 text-[13px] italic text-[var(--vocab-muted-fg)]">
                    «{truncateContext(item.context)}»
                  </span>
                  )
                : <span className="text-[var(--vocab-muted-fg)]">—</span>}
            </div>
            <div>
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
    </div>
  )
}
