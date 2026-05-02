import { createRoute } from '@tanstack/react-router'

import { OnboardingForm } from '@/features/onboarding/OnboardingForm'

import { rootRoute } from './__rootRoute'

export const onboardingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/onboarding',
  component: () => (
    <div className="min-h-screen flex items-center justify-center p-4 bg-background">
      <OnboardingForm />
    </div>
  ),
})
