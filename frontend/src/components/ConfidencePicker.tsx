import { Check, Trash2 } from 'lucide-react'

const PILLS = [1, 2, 3, 4] as const

interface Props {
  status: 'new' | 'tracked' | 'known' | 'ignored'
  confidence: number | null
  onSelect: (status: 'tracked' | 'known' | 'ignored', confidence: number | null) => void
  size?: 'md' | 'sm'
}

/** Shared status/confidence widget: 🗑 [1][2][3][4] ✓ (ADR-0005 + FLQ-5 §2). */
export function ConfidencePicker({ status, confidence, onSelect, size = 'md' }: Props) {
  const pill = size === 'md' ? 'h-8 w-8 text-sm' : 'h-7 w-7 text-xs'
  const icon = size === 'md' ? 'h-4 w-4' : 'h-3.5 w-3.5'
  const iconBtn = size === 'md' ? 'p-2' : 'p-[7px]'
  const defaultPill =
    'border-[var(--vocab-picker-border)] bg-white text-[var(--vocab-muted-fg)] hover:bg-accent'
  return (
    <div className="flex items-center justify-between gap-2">
      <button
        type="button" aria-label="Игнорировать" title="Игнорировать"
        onClick={() => onSelect('ignored', null)}
        className={`rounded-full border ${iconBtn} hover:bg-accent ${status === 'ignored' ? 'border-foreground' : 'border-border'}`}
      >
        <Trash2 className={icon} />
      </button>
      <div className="flex items-center gap-1">
        {PILLS.map((n) => (
          <button
            key={n} type="button" aria-label={`Уровень ${n}`} title={`Уверенность ${n}/4`}
            onClick={() => onSelect('tracked', n)}
            className={`flex ${pill} items-center justify-center rounded-full border ${
              status === 'tracked' && confidence === n
                ? 'bg-[var(--vocab-picker-active-bg)] text-[var(--vocab-picker-active-fg)] border-transparent font-semibold'
                : defaultPill
            }`}
          >
            {n}
          </button>
        ))}
      </div>
      <button
        type="button" aria-label="Изучено" title="Изучено"
        onClick={() => onSelect('known', null)}
        className={`rounded-full border ${iconBtn} ${
          status === 'known'
            ? 'bg-[var(--vocab-known-bg)] text-white border-transparent'
            : defaultPill
        }`}
      >
        <Check className={icon} />
      </button>
    </div>
  )
}
