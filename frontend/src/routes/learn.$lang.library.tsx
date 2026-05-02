import { createRoute } from '@tanstack/react-router'

import { FilterRow } from '@/features/library/FilterRow'

import { learnLangRoute } from './learn.$lang'

export const learnLibraryRoute = createRoute({
  getParentRoute: () => learnLangRoute,
  path: 'library',
  component: function LibraryRoute() {
    return (
      <div className="mx-auto max-w-screen-2xl px-6">
        <FilterRow />
        <div className="text-muted-foreground">Cards coming in next task.</div>
      </div>
    )
  },
})
