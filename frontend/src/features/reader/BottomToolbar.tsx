import { cn } from '@/lib/utils'

import type { ViewMode } from './readerStore'

interface Props {
  mode: ViewMode
  onToggleMode: () => void
  /** Сжать сетку действий на ширину открытой боковой панели WordCard. */
  panelOpen?: boolean
}

interface ActionProps {
  icon: string
  label: string
  onClick?: () => void
  disabled?: boolean
  title?: string
}

function Action({ icon, label, onClick, disabled, title }: ActionProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="flex h-14 flex-col items-center justify-center gap-1 rounded-md text-sm hover:bg-accent disabled:opacity-50"
    >
      <span aria-hidden className="text-lg leading-none">
        {icon}
      </span>
      <span>{label}</span>
    </button>
  )
}

export function BottomToolbar({ mode, onToggleMode, panelOpen }: Props) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-[var(--z-fixed)] border-t border-border bg-background">
      <div
        className={cn(
          'mx-auto grid max-w-screen-2xl grid-cols-3 px-6 py-3',
          panelOpen && 'md:pr-[344px]',
        )}
      >
        <Action icon="♪" label="Сгенерировать аудио" disabled title="Скоро" />
        <Action
          icon="📖"
          label={mode === 'sentence' ? 'Показать всю страницу' : 'По предложениям'}
          onClick={onToggleMode}
        />
        <Action icon="✓" label="Повторить лексику" disabled title="Скоро (FLQ-7)" />
      </div>
    </div>
  )
}
