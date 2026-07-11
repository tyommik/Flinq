import { Link, useParams } from '@tanstack/react-router'

import { LanguagePicker } from './LanguagePicker'
import { AvatarMenu } from './AvatarMenu'

export function AppTopBar() {
  const params = useParams({ strict: false }) as { lang?: string }
  const lang = params.lang ?? 'en'

  return (
    <header className="h-16 border-b border-border bg-background">
      <div className="mx-auto flex h-full max-w-screen-2xl items-center gap-6 px-6">
        <Link
          to="/learn/$lang/library"
          params={{ lang }}
          className="text-2xl font-bold tracking-tight"
        >
          Flinq
        </Link>
        <LanguagePicker />
        <nav className="ml-4 flex items-center gap-1">
          <Link
            to="/learn/$lang/library"
            params={{ lang }}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-foreground hover:bg-accent [&.active]:border-b-2 [&.active]:border-primary"
            activeProps={{ className: 'active' }}
          >
            Библиотека
          </Link>
          <Link
            to="/learn/$lang/vocabulary"
            params={{ lang }}
            search={{ tab: 'all' }}
            activeOptions={{ includeSearch: false }}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-foreground hover:bg-accent [&.active]:border-b-2 [&.active]:border-primary"
            activeProps={{ className: 'active' }}
          >
            Словарь
          </Link>
        </nav>
        <div className="ml-auto">
          <AvatarMenu />
        </div>
      </div>
    </header>
  )
}
