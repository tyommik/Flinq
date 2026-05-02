import { createRoute } from '@tanstack/react-router'

import { IndexRoute } from './routes/index'
import { rootRoute } from './routes/__rootRoute'
import { loginRoute } from './routes/login'
import { registerRoute } from './routes/register'
import { onboardingRoute } from './routes/onboarding'
import { learnLangLibraryStubRoute } from './routes/learn-stub'

export { rootRoute } from './routes/__rootRoute'
export type { RouterContext } from './routes/__rootRoute'

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: IndexRoute,
})

export const routeTree = rootRoute.addChildren([
  indexRoute,
  loginRoute,
  registerRoute,
  onboardingRoute,
  learnLangLibraryStubRoute,
])
