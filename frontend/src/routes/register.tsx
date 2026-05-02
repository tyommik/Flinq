import { createRoute } from '@tanstack/react-router'

import { RegisterForm } from '@/features/auth/RegisterForm'

import { rootRoute } from './__rootRoute'

export const registerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/register',
  component: () => (
    <div className="min-h-screen flex items-center justify-center p-4 bg-background">
      <RegisterForm />
    </div>
  ),
})
