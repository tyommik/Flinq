import { createRoute } from '@tanstack/react-router'

import { ProtectedRoute } from '@/components/ProtectedRoute'

import { rootRoute } from './__rootRoute'

export const learnLangLibraryStubRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/learn/$lang/library',
  component: function LearnLangLibraryStub() {
    return (
      <ProtectedRoute>
        <div className="min-h-screen flex items-center justify-center p-4 bg-background">
          <p className="text-muted-foreground">Library — coming in Task 26.</p>
        </div>
      </ProtectedRoute>
    )
  },
})
