import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, createRoute } from '@tanstack/react-router'

import { RootLayout } from './routes/__root'
import { IndexRoute } from './routes/index'

export interface RouterContext {
  queryClient: QueryClient
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: IndexRoute,
})

export const routeTree = rootRoute.addChildren([indexRoute])