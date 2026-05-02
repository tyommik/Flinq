import { Outlet, createRoute, redirect } from '@tanstack/react-router'

import { ProtectedRoute } from '@/components/ProtectedRoute'
import { AppTopBar } from '@/components/AppTopBar'

import { rootRoute } from './__rootRoute'

const SUPPORTED_LANGS = new Set(['en', 'ru', 'pt'])

export const learnLangRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/learn/$lang',
  beforeLoad: ({ params }) => {
    if (!SUPPORTED_LANGS.has(params.lang)) {
      throw redirect({ to: '/' })
    }
  },
  component: function LearnLangLayout() {
    return (
      <ProtectedRoute>
        <div className="min-h-screen bg-background">
          <AppTopBar />
          <main>
            <Outlet />
          </main>
        </div>
      </ProtectedRoute>
    )
  },
})
