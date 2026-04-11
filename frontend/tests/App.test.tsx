import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { IndexRoute } from '@/routes/index'

function renderWithClient(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('IndexRoute', () => {
  it('renders the Flinq title', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: () => Promise.resolve({ status: 'ok', version: '0.0.1' }),
        }),
      ),
    )

    renderWithClient(<IndexRoute />)

    expect(screen.getByRole('heading', { level: 1, name: /flinq/i })).toBeInTheDocument()
  })

  it('displays the backend version after a successful health fetch', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: () => Promise.resolve({ status: 'ok', version: '0.0.1' }),
        }),
      ),
    )

    renderWithClient(<IndexRoute />)

    await waitFor(() => {
      expect(screen.getByText(/version=0\.0\.1/)).toBeInTheDocument()
    })
  })
})