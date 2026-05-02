import { useLibraryStore } from './libraryStore'

const TABS = [
  { id: 'continue' as const, label: 'Продолжить изучение' },
  { id: 'lessons' as const, label: 'Уроки' },
]

export function SubTabs() {
  const tab = useLibraryStore((s) => s.tab)
  const setTab = useLibraryStore((s) => s.setTab)

  return (
    <nav className="flex items-center gap-6 border-b border-border">
      {TABS.map((t) => {
        const active = tab === t.id
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => { setTab(t.id) }}
            className={[
              'relative -mb-px py-3 text-sm transition-colors',
              active
                ? 'font-medium text-foreground'
                : 'text-muted-foreground hover:text-foreground',
            ].join(' ')}
          >
            {t.label}
            {active && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 bg-primary" />
            )}
          </button>
        )
      })}
    </nav>
  )
}
