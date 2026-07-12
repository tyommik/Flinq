import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Token, TokenStatusEntry } from '@/api/reader'

import { TokenSpan } from './TokenSpan'

const word: Token = { t: 'Hello', n: 'hello', i: 0 }

describe('TokenSpan', () => {
  it('renders a statusless word with the new-word background', () => {
    render(<TokenSpan token={word} />)
    expect(screen.getByText('Hello').className).toContain('bg-[var(--reader-new-bg)]')
  })

  it('renders a tracked word with the tracked background', () => {
    const status: TokenStatusEntry = { s: 'tracked', c: 2 }
    render(<TokenSpan token={word} status={status} />)
    expect(screen.getByText('Hello').className).toContain('bg-[var(--reader-tracked-bg)]')
  })

  it('renders a known word with no status background', () => {
    const status: TokenStatusEntry = { s: 'known' }
    render(<TokenSpan token={word} status={status} />)
    const el = screen.getByText('Hello')
    expect(el.className).not.toContain('bg-[var(--reader-new-bg)]')
    expect(el.className).not.toContain('bg-[var(--reader-tracked-bg)]')
  })

  it('renders an ignored word with no status background', () => {
    const status: TokenStatusEntry = { s: 'ignored' }
    render(<TokenSpan token={word} status={status} />)
    const el = screen.getByText('Hello')
    expect(el.className).not.toContain('bg-[var(--reader-new-bg)]')
    expect(el.className).not.toContain('bg-[var(--reader-tracked-bg)]')
  })

  it('renders a tracked word with confidence 0 as tracked (yellow) — ADR-0005: uniform yellow regardless of confidence', () => {
    render(<TokenSpan token={{ t: 'Hola', n: 'hola', i: 3 }} status={{ s: 'tracked', c: 0 }} />)
    const el = screen.getByText('Hola')
    expect(el.className).toContain('bg-[var(--reader-tracked-bg)]')
    expect(el.className).not.toContain('bg-[var(--reader-new-bg)]')
  })

  it('renders a tracked word with a missing confidence as tracked (yellow)', () => {
    render(<TokenSpan token={{ t: 'Hola', n: 'hola', i: 3 }} status={{ s: 'tracked' }} />)
    expect(screen.getByText('Hola').className).toContain('bg-[var(--reader-tracked-bg)]')
  })

  it('renders a whitespace token as its exact whitespace text', () => {
    const { container } = render(<TokenSpan token={{ ws: '  ' }} />)
    const el = container.querySelector('span')
    expect(el?.textContent).toBe('  ')
    expect(container.textContent).toBe('  ')
  })

  it('renders a punctuation token as a plain span', () => {
    render(<TokenSpan token={{ p: '.' }} />)
    const el = screen.getByText('.')
    expect(el.tagName).toBe('SPAN')
    expect(el.className).toBe('')
  })

  it('fires onWordClick with the token object when clicked', () => {
    const onWordClick = vi.fn()
    render(<TokenSpan token={word} onWordClick={onWordClick} />)
    screen.getByText('Hello').click()
    expect(onWordClick).toHaveBeenCalledWith(word)
  })

  it('applies drag-selection background', () => {
    render(<TokenSpan token={{ t: 'far', n: 'far', i: 1 }} dragSelected />)
    expect(screen.getByText('far').className).toContain('bg-primary/20')
  })

  it('stops click propagation so PhraseSpan does not also fire', () => {
    const outer = vi.fn()
    render(
      <div onClick={outer}>
        <TokenSpan token={{ t: 'far', n: 'far', i: 1 }} onWordClick={() => {}} />
      </div>,
    )
    fireEvent.click(screen.getByText('far'))
    expect(outer).not.toHaveBeenCalled()
  })
})
