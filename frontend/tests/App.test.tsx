import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import { meApi } from '@/api/me'
import { IndexRoute } from '@/routes/index'
import { useUserStore } from '@/stores/userStore'
import type { MeResponse } from '@/api/me'

const navigate = vi.fn()

// vi.mock calls are hoisted above these imports by vitest, so IndexRoute
// picks up the mocked router/api modules below.
vi.mock('@tanstack/react-router', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-router')>(
    '@tanstack/react-router',
  )
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('@/api/me', () => ({
  meApi: { get: vi.fn() },
}))

function renderIndexRoute() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <IndexRoute />
    </QueryClientProvider>,
  )
}

function meResponse(overrides: Partial<MeResponse> = {}): MeResponse {
  return {
    id: 'user-1',
    email: 'user@example.com',
    role: 'learner',
    display_name: 'User',
    ui_language_code: 'en',
    learning_languages: ['en'],
    last_learning_language_code: null,
    needs_onboarding: false,
    onboarded_at: null,
    ...overrides,
  }
}

describe('IndexRoute', () => {
  beforeEach(() => {
    navigate.mockClear()
    useUserStore.getState().reset()
  })

  afterEach(() => {
    vi.mocked(meApi.get).mockReset()
  })

  it('redirects to /onboarding when the session needs onboarding', async () => {
    vi.mocked(meApi.get).mockResolvedValue(meResponse({ needs_onboarding: true }))

    renderIndexRoute()

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith({ to: '/onboarding', replace: true })
    })
  })

  it('redirects to the last learning language library on an active session', async () => {
    vi.mocked(meApi.get).mockResolvedValue(
      meResponse({
        learning_languages: ['en', 'es'],
        last_learning_language_code: 'es',
      }),
    )

    renderIndexRoute()

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith({
        to: '/learn/$lang/library',
        params: { lang: 'es' },
        replace: true,
      })
    })
  })

  it('falls back to the first learning language when none was last selected', async () => {
    vi.mocked(meApi.get).mockResolvedValue(
      meResponse({
        learning_languages: ['de', 'fr'],
        last_learning_language_code: null,
      }),
    )

    renderIndexRoute()

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith({
        to: '/learn/$lang/library',
        params: { lang: 'de' },
        replace: true,
      })
    })
  })

  it('redirects to /login when the session check returns 401', async () => {
    vi.mocked(meApi.get).mockRejectedValue(new ApiError(401, 'Unauthorized'))

    renderIndexRoute()

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith({ to: '/login', replace: true })
    })
  })
})
