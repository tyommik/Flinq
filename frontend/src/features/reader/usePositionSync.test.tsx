import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/reader', () => ({
  readerApi: {
    putPosition: vi.fn(),
  },
}))

import { readerApi } from '@/api/reader'

import { usePositionSync } from './usePositionSync'

/**
 * TanStack Query v5 calls `mutationFn(variables, context)` — a second,
 * internal context argument is always present, so we assert on each call's
 * first argument rather than the full call signature.
 */
function callArgs(mockFn: { mock: { calls: unknown[][] } }): unknown[] {
  return mockFn.mock.calls.map((call) => call[0])
}

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

interface HookProps {
  currentSegmentId: string | null
  currentOrdinal: number | null
}

function renderPositionSync(initial: HookProps) {
  return renderHook((props: HookProps) => usePositionSync({ lessonId: 'lesson-1', mode: 'page', enabled: true, ...props }), {
    initialProps: initial,
    wrapper,
  })
}

describe('usePositionSync', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(readerApi.putPosition).mockClear()
    vi.mocked(readerApi.putPosition).mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('flushes the latest pending payload on unmount before the 2s debounce fires', async () => {
    const { rerender, unmount } = renderPositionSync({ currentSegmentId: 'seg-1', currentOrdinal: 0 })

    rerender({ currentSegmentId: 'seg-2', currentOrdinal: 10 })
    rerender({ currentSegmentId: 'seg-3', currentOrdinal: 20 })

    await vi.advanceTimersByTimeAsync(500)

    unmount()
    await vi.advanceTimersByTimeAsync(0)

    expect(readerApi.putPosition).toHaveBeenCalledTimes(1)
    expect(callArgs(vi.mocked(readerApi.putPosition))).toEqual([
      {
        lesson_id: 'lesson-1',
        view_mode: 'page',
        current_segment_id: 'seg-3',
        current_token_ordinal: 20,
      },
    ])
  })

  it('sends exactly once when the debounce timer fires, then nothing more on unmount', async () => {
    const { unmount } = renderPositionSync({ currentSegmentId: 'seg-1', currentOrdinal: 0 })

    await vi.advanceTimersByTimeAsync(2000)

    expect(readerApi.putPosition).toHaveBeenCalledTimes(1)

    unmount()
    await vi.advanceTimersByTimeAsync(0)

    expect(readerApi.putPosition).toHaveBeenCalledTimes(1)
  })
})
