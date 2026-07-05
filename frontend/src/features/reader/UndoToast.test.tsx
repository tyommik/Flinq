import { render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { UndoToast } from './UndoToast'

describe('UndoToast', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('auto-dismisses 6s from mount and is NOT extended by parent re-renders with a new onDismiss', async () => {
    const onDismiss1 = vi.fn()
    const onDismiss2 = vi.fn()
    const { rerender } = render(<UndoToast count={2} onUndo={vi.fn()} onDismiss={onDismiss1} />)

    await vi.advanceTimersByTimeAsync(3000)
    expect(onDismiss1).not.toHaveBeenCalled()

    // Parent re-renders with a brand-new inline onDismiss (simulating a
    // ReaderPage re-render) — this must NOT re-arm the 6s timer.
    rerender(<UndoToast count={2} onUndo={vi.fn()} onDismiss={onDismiss2} />)

    await vi.advanceTimersByTimeAsync(3000)

    expect(onDismiss1).not.toHaveBeenCalled()
    expect(onDismiss2).toHaveBeenCalledTimes(1)
  })

  it('does not call onDismiss and leaves no timer leak when unmounted before 6s', async () => {
    const onDismiss = vi.fn()
    const clearSpy = vi.spyOn(window, 'clearTimeout')
    const { unmount } = render(<UndoToast count={1} onUndo={vi.fn()} onDismiss={onDismiss} />)

    await vi.advanceTimersByTimeAsync(3000)
    unmount()
    await vi.advanceTimersByTimeAsync(10000)

    expect(onDismiss).not.toHaveBeenCalled()
    expect(clearSpy).toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)

    clearSpy.mockRestore()
  })
})
