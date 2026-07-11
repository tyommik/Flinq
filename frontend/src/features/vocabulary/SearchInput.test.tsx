import { act, render, screen, fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SearchInput } from './SearchInput'
import { useVocabularyStore } from './vocabularyStore'

// Captured once, before any test mutates store actions (e.g. replacing setQ
// with a vi.fn()), so beforeEach can fully restore the pristine store —
// including real action implementations — instead of leaking mocks between
// tests.
const initialState = useVocabularyStore.getState()

describe('SearchInput', () => {
  beforeEach(() => {
    useVocabularyStore.setState(initialState, true)
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not call setQ before 300ms and calls it once after, with the typed value', async () => {
    render(<SearchInput />)
    const input = screen.getByPlaceholderText('Поиск в словаре')

    fireEvent.change(input, { target: { value: 'cas' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(299) })
    expect(useVocabularyStore.getState().q).toBe('')

    fireEvent.change(input, { target: { value: 'casa' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(300) })

    expect(useVocabularyStore.getState().q).toBe('casa')
  })

  it('debounces rapid keystrokes into a single store update', async () => {
    const setQ = vi.fn()
    useVocabularyStore.setState({ setQ })
    render(<SearchInput />)
    const input = screen.getByPlaceholderText('Поиск в словаре')

    fireEvent.change(input, { target: { value: 'c' } })
    await vi.advanceTimersByTimeAsync(100)
    fireEvent.change(input, { target: { value: 'ca' } })
    await vi.advanceTimersByTimeAsync(100)
    fireEvent.change(input, { target: { value: 'cas' } })

    expect(setQ).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(300)

    expect(setQ).toHaveBeenCalledTimes(1)
    expect(setQ).toHaveBeenCalledWith('cas')
  })

  it('does not call setQ on mount when the input value already equals the store value', async () => {
    const setQ = vi.fn()
    useVocabularyStore.setState({ q: 'casa', setQ })
    render(<SearchInput />)

    await act(async () => { await vi.advanceTimersByTimeAsync(300) })

    expect(setQ).not.toHaveBeenCalled()
  })

  it('syncs the input from an external store reset and does not re-apply the stale value', async () => {
    const setQSpy = vi.spyOn(useVocabularyStore.getState(), 'setQ')
    render(<SearchInput />)
    const input = screen.getByPlaceholderText('Поиск в словаре') as HTMLInputElement

    fireEvent.change(input, { target: { value: 'zzz' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(300) })

    expect(setQSpy).toHaveBeenCalledWith('zzz')
    expect(useVocabularyStore.getState().q).toBe('zzz')
    expect(input.value).toBe('zzz')

    act(() => { useVocabularyStore.getState().resetFilters() })

    expect(useVocabularyStore.getState().q).toBe('')
    expect(input.value).toBe('')

    setQSpy.mockClear()
    await act(async () => { await vi.advanceTimersByTimeAsync(400) })

    expect(setQSpy).not.toHaveBeenCalledWith('zzz')
    expect(input.value).toBe('')
  })
})
