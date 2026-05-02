import { useQuery } from '@tanstack/react-query'
import { createRoute, useParams } from '@tanstack/react-router'

import { lessonsApi } from '@/api/lessons'

import { FilterRow } from '@/features/library/FilterRow'
import { LessonCarousel } from '@/features/library/LessonCarousel'
import { LibraryEmptyState } from '@/features/library/LibraryEmptyState'
import { SubTabs } from '@/features/library/SubTabs'
import { useLibraryStore } from '@/features/library/libraryStore'

import { learnLangRoute } from './learn.$lang'

export const learnLibraryRoute = createRoute({
  getParentRoute: () => learnLangRoute,
  path: 'library',
  component: function LibraryView() {
    const params = useParams({ from: '/learn/$lang/library' })
    const lang = params.lang
    const tab = useLibraryStore((s) => s.tab)
    const search = useLibraryStore((s) => s.search)
    const visibility = useLibraryStore((s) => s.visibility)
    const page = useLibraryStore((s) => s.page)

    const { data, isLoading, isError } = useQuery({
      queryKey: ['lessons', lang, tab, search, visibility, page],
      queryFn: () => lessonsApi.list(lang, { tab, q: search || undefined, visibility, page }),
    })

    return (
      <div className="mx-auto max-w-screen-2xl px-6">
        <FilterRow />
        <SubTabs />
        <div className="py-6">
          {isLoading && (
            <p className="text-muted-foreground">Загрузка…</p>
          )}
          {isError && (
            <p className="text-destructive">Ошибка загрузки уроков</p>
          )}
          {data && data.items.length > 0 && <LessonCarousel items={data.items} />}
          {data && data.items.length === 0 && <LibraryEmptyState />}
        </div>
      </div>
    )
  },
})
