import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ConfidencePicker } from './ConfidencePicker'

describe('ConfidencePicker', () => {
  it('fires tracked/N, known and ignored selections', () => {
    const onSelect = vi.fn()
    render(<ConfidencePicker status="tracked" confidence={2} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: 'Уровень 3' }))
    expect(onSelect).toHaveBeenCalledWith('tracked', 3)
    fireEvent.click(screen.getByRole('button', { name: 'Изучено' }))
    expect(onSelect).toHaveBeenCalledWith('known', null)
    fireEvent.click(screen.getByRole('button', { name: 'Игнорировать' }))
    expect(onSelect).toHaveBeenCalledWith('ignored', null)
  })

  it('highlights the active pill and none for confidence 0', () => {
    const { rerender } = render(
      <ConfidencePicker status="tracked" confidence={2} onSelect={() => {}} />,
    )
    expect(screen.getByRole('button', { name: 'Уровень 2' }).className).toContain(
      '--vocab-picker-active-bg',
    )
    rerender(<ConfidencePicker status="tracked" confidence={0} onSelect={() => {}} />)
    for (const n of [1, 2, 3, 4]) {
      expect(screen.getByRole('button', { name: `Уровень ${n}` }).className).not.toContain(
        '--vocab-picker-active-bg',
      )
    }
  })

  it('highlights the known button with the vocab-known token when active', () => {
    render(<ConfidencePicker status="known" confidence={null} onSelect={() => {}} />)
    expect(screen.getByRole('button', { name: 'Изучено' }).className).toContain(
      '--vocab-known-bg',
    )
  })
})
