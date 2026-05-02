import { createRoute } from '@tanstack/react-router'

import { LoginForm } from '@/features/auth/LoginForm'

import { rootRoute } from './__rootRoute'

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: () => (
    <div className="min-h-screen flex items-center justify-center p-4 bg-background">
      <LoginForm />
    </div>
  ),
})
