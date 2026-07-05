import type { ViewMode } from './readerStore'

interface Props {
  mode: ViewMode
  onToggleMode: () => void
}

export function BottomToolbar({ mode, onToggleMode }: Props) {
  return (
    <div className="flex items-center justify-between border-t border-border py-3">
      <button
        type="button"
        onClick={onToggleMode}
        className="rounded-md px-3 py-1.5 text-sm font-medium hover:bg-accent"
      >
        {mode === 'sentence' ? 'Показать весь текст' : 'По предложениям'}
      </button>
      <button
        type="button"
        disabled
        title="Скоро (FLQ-7)"
        className="rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground opacity-50"
      >
        Повторение
      </button>
    </div>
  )
}
