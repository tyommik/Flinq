if (typeof window !== 'undefined' && !window.PointerEvent) {
  class PointerEventPolyfill extends MouseEvent {
    pointerType: string
    constructor(type: string, init: MouseEventInit & { pointerType?: string } = {}) {
      super(type, init)
      this.pointerType = init.pointerType ?? 'mouse'
    }
  }
  window.PointerEvent = PointerEventPolyfill as unknown as typeof PointerEvent
}

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Sentence, Token } from '@/api/reader'

import { MAX_PHRASE_WORDS, usePhraseSelection, type DragRange } from './usePhraseSelection'

const w = (t: string, i: number): Token => ({ t, n: t.toLowerCase(), i })
const ws: Token = { ws: ' ' }

function sentence(seg: string, words: string[], firstOrdinal: number): Sentence {
  const tokens: Token[] = []
  words.forEach((word, k) => {
    if (k > 0) tokens.push(ws)
    tokens.push(w(word, firstOrdinal + k))
  })
  return {
    seg_id: seg, index: 0, text: words.join(' '),
    normalized_text: words.join(' ').toLowerCase(), tokens,
  }
}

const s1 = sentence('s1', ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'], 0)
const s2 = sentence('s2', ['other', 'words'], 10)

function Harness({
  onSelect,
  enabled = true,
  onWordClick,
}: {
  onSelect: (r: DragRange, s: Sentence) => void
  enabled?: boolean
  onWordClick?: (ordinal: number) => void
}) {
  const { dragRange, containerProps } = usePhraseSelection({
    enabled,
    sentences: [s1, s2],
    onSelect,
  })
  return (
    <div data-testid="container" {...containerProps}>
      <span data-testid="drag-range">{dragRange ? `${dragRange.from}-${dragRange.to}` : ''}</span>
      {[s1, s2].flatMap((s) =>
        s.tokens.map((tok, i) =>
          't' in tok ? (
            <span
              key={`${s.seg_id}-${i}`}
              data-ordinal={tok.i}
              data-testid={`w-${tok.i}`}
              onClick={() => onWordClick?.(tok.i)}
            >
              {tok.t}
            </span>
          ) : (
            <span key={`${s.seg_id}-${i}`}> </span>
          ),
        ),
      )}
    </div>
  )
}

function pointer(type: 'pointerdown' | 'pointerover' | 'pointerup', el: Element) {
  fireEvent(
    el,
    new PointerEvent(type, {
      bubbles: true,
      pointerType: 'mouse',
      button: 0,
      // Реалистичные buttons: во время down/over основная кнопка нажата,
      // к моменту up — уже отпущена.
      buttons: type === 'pointerup' ? 0 : 1,
    }),
  )
}

describe('usePhraseSelection', () => {
  it('drag over two words selects the range and fires onSelect on pointerup', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-1'))
    pointer('pointerover', screen.getByTestId('w-3'))
    expect(screen.getByTestId('drag-range').textContent).toBe('1-3')
    pointer('pointerup', screen.getByTestId('w-3'))
    expect(onSelect).toHaveBeenCalledWith({ from: 1, to: 3 }, s1)
  })

  it('plain click (no drag) does not fire onSelect', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-1'))
    pointer('pointerup', screen.getByTestId('w-1'))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('reverse drag normalizes the range', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-5'))
    pointer('pointerover', screen.getByTestId('w-2'))
    pointer('pointerup', screen.getByTestId('w-2'))
    expect(onSelect).toHaveBeenCalledWith({ from: 2, to: 5 }, s1)
  })

  it(`clamps to ${MAX_PHRASE_WORDS} words`, () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-0'))
    pointer('pointerover', screen.getByTestId('w-9')) // 10 слов
    pointer('pointerup', screen.getByTestId('w-9'))
    expect(onSelect).toHaveBeenCalledWith({ from: 0, to: 7 }, s1)
  })

  it('clamps to the anchor sentence', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-8'))
    pointer('pointerover', screen.getByTestId('w-11')) // слово из s2
    pointer('pointerup', screen.getByTestId('w-11'))
    expect(onSelect).toHaveBeenCalledWith({ from: 8, to: 9 }, s1)
  })

  it('Escape cancels the drag', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-1'))
    pointer('pointerover', screen.getByTestId('w-3'))
    fireEvent.keyDown(window, { key: 'Escape' })
    pointer('pointerup', screen.getByTestId('w-3'))
    expect(onSelect).not.toHaveBeenCalled()
    expect(screen.getByTestId('drag-range').textContent).toBe('')
  })

  it('touch pointer is ignored', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    fireEvent(
      screen.getByTestId('w-1'),
      new PointerEvent('pointerdown', { bubbles: true, pointerType: 'touch' }),
    )
    pointer('pointerover', screen.getByTestId('w-3'))
    pointer('pointerup', screen.getByTestId('w-3'))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('releasing the pointer outside the container still finalizes the drag', () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    pointer('pointerdown', screen.getByTestId('w-1'))
    pointer('pointerover', screen.getByTestId('w-3'))
    expect(screen.getByTestId('drag-range').textContent).toBe('1-3')
    fireEvent(window, new PointerEvent('pointerup', { bubbles: true }))
    expect(onSelect).toHaveBeenCalledWith({ from: 1, to: 3 }, s1)
    expect(screen.getByTestId('drag-range').textContent).toBe('')
  })

  it('suppresses the synthetic click after a completed drag, but only once', () => {
    const onSelect = vi.fn()
    const onWordClick = vi.fn()
    render(<Harness onSelect={onSelect} onWordClick={onWordClick} />)
    pointer('pointerdown', screen.getByTestId('w-1'))
    pointer('pointerover', screen.getByTestId('w-3'))
    pointer('pointerup', screen.getByTestId('w-3'))
    expect(onSelect).toHaveBeenCalledWith({ from: 1, to: 3 }, s1)

    fireEvent.click(screen.getByTestId('w-3'))
    expect(onWordClick).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('w-3'))
    expect(onWordClick).toHaveBeenCalledTimes(1)
  })

  it('release outside before any drag does not leave a live anchor (no phantom drag)', () => {
    const onSelect = vi.fn()
    const onWordClick = vi.fn()
    render(<Harness onSelect={onSelect} onWordClick={onWordClick} />)
    pointer('pointerdown', screen.getByTestId('w-1'))
    // Уход из контейнера и отпускание кнопки снаружи: drag не начался,
    // window-фоллбек не подключён, якорь остаётся жить.
    fireEvent(window, new PointerEvent('pointerup', { bubbles: true }))
    // Возврат курсора на слова уже без нажатой кнопки.
    fireEvent(
      screen.getByTestId('w-3'),
      new PointerEvent('pointerover', {
        bubbles: true,
        pointerType: 'mouse',
        buttons: 0,
      }),
    )
    expect(screen.getByTestId('drag-range').textContent).toBe('')
    fireEvent.click(screen.getByTestId('w-3'))
    expect(onSelect).not.toHaveBeenCalled()
    expect(onWordClick).toHaveBeenCalledTimes(1)
  })

  it('does not suppress a plain click (no drag)', () => {
    const onSelect = vi.fn()
    const onWordClick = vi.fn()
    render(<Harness onSelect={onSelect} onWordClick={onWordClick} />)
    pointer('pointerdown', screen.getByTestId('w-1'))
    pointer('pointerup', screen.getByTestId('w-1'))
    expect(onSelect).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('w-1'))
    expect(onWordClick).toHaveBeenCalledTimes(1)
  })
})
