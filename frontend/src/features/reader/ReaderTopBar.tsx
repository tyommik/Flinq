import { PanelLeft, X } from 'lucide-react'
import { useNavigate } from '@tanstack/react-router'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

import { useReaderStore, type ViewMode } from './readerStore'

interface Props {
  lang: string
  title: string
  progressPercent: number
  mode: ViewMode
  sidebarOpen: boolean
  onToggleSidebar: () => void
}

const SIZE_OPTIONS = [
  { label: 'A', size: 0 as const },
  { label: 'A', size: 1 as const },
  { label: 'A', size: 2 as const },
]

const LINE_HEIGHT_OPTIONS = [
  { label: 'Компактно', lineHeight: 0 as const },
  { label: 'Обычно', lineHeight: 1 as const },
  { label: 'Просторно', lineHeight: 2 as const },
]

export function ReaderTopBar({
  lang,
  title,
  progressPercent,
  mode,
  sidebarOpen,
  onToggleSidebar,
}: Props) {
  const navigate = useNavigate()
  const font = useReaderStore((s) => s.font)
  const setFont = useReaderStore((s) => s.setFont)

  return (
    <div className="flex items-center gap-4 border-b border-border py-3">
      <button
        type="button"
        aria-label="Закрыть"
        onClick={() => {
          void navigate({ to: '/learn/$lang/library', params: { lang } })
        }}
        className="rounded-md p-2 hover:bg-accent"
      >
        <X className="h-5 w-5" />
      </button>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{title}</p>
        <div className="mt-1 h-1.5 w-full rounded-full bg-muted">
          <div
            className="h-1.5 rounded-full bg-primary"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="rounded-md px-2 py-1 text-sm font-medium hover:bg-accent"
          >
            Aa
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <div className="flex gap-1 p-1">
            {SIZE_OPTIONS.map((opt) => (
              <DropdownMenuItem
                key={opt.size}
                onSelect={(e) => {
                  e.preventDefault()
                  setFont({ size: opt.size })
                }}
                className={cn(font.size === opt.size && 'bg-accent')}
              >
                {opt.label}
              </DropdownMenuItem>
            ))}
          </div>
          <div className="flex flex-col gap-1 p-1">
            {LINE_HEIGHT_OPTIONS.map((opt) => (
              <DropdownMenuItem
                key={opt.lineHeight}
                onSelect={(e) => {
                  e.preventDefault()
                  setFont({ lineHeight: opt.lineHeight })
                }}
                className={cn(font.lineHeight === opt.lineHeight && 'bg-accent')}
              >
                {opt.label}
              </DropdownMenuItem>
            ))}
          </div>
          <DropdownMenuItem
            onSelect={(e) => {
              e.preventDefault()
              setFont({ serif: !font.serif })
            }}
            className={cn(font.serif && 'bg-accent')}
          >
            Serif
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {mode === 'page' && (
        <button
          type="button"
          aria-label="Оглавление"
          aria-pressed={sidebarOpen}
          onClick={onToggleSidebar}
          className="rounded-md p-2 hover:bg-accent"
        >
          <PanelLeft className="h-5 w-5" />
        </button>
      )}
    </div>
  )
}
