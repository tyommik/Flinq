import type { MouseEventHandler, PointerEventHandler } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { isWord, type Sentence } from '@/api/reader'

/** Диапазон слово-ординалов, включительно, from <= to. */
export interface DragRange {
  from: number
  to: number
}

export const MAX_PHRASE_WORDS = 8

interface Anchor {
  ordinal: number
  sentence: Sentence
  /** Ординалы слов предложения якоря по возрастанию. Пунктуация тоже
      получает свой ординал у бэкенда, поэтому эта последовательность
      содержит "дыры" и не является непрерывным диапазоном. Непустой по
      построению — якорь ставится только если в предложении нашлось слово
      с этим ординалом (см. onPointerDown). */
  wordOrdinals: number[]
}

interface Params {
  enabled: boolean
  sentences: Sentence[]
  onSelect: (range: DragRange, sentence: Sentence) => void
}

// Находит индекс слова с данным ординалом. Если такого слова в предложении
// нет (при текущей разметке DOM это не должно происходить — пунктуация не
// несёт data-ordinal, поэтому под курсором никогда не окажется её ординал),
// подбираем ближайшее слово по направлению движения курсора.
function resolveWordIndex(wordOrdinals: number[], target: number, forward: boolean): number {
  const exact = wordOrdinals.indexOf(target)
  if (exact !== -1) return exact
  if (forward) {
    // последний индекс с wordOrdinals[i] <= target
    let idx = 0
    for (const [i, ord] of wordOrdinals.entries()) {
      if (ord <= target) idx = i
    }
    return idx
  }
  // первый индекс с wordOrdinals[i] >= target
  for (const [i, ord] of wordOrdinals.entries()) {
    if (ord >= target) return i
  }
  return wordOrdinals.length - 1
}

// Лимит в 8 слов считается в индексном пространстве wordOrdinals, а не
// арифметикой над ординалами — иначе пунктуация внутри диапазона (у которой
// тоже есть свой ординал) отъедала бы слот у настоящего слова.
function clampRange(anchor: Anchor, target: number): DragRange {
  const { wordOrdinals, ordinal } = anchor
  const first = Math.min(...wordOrdinals)
  const last = Math.max(...wordOrdinals)
  const clamped = Math.min(Math.max(target, first), last)

  const ai = wordOrdinals.indexOf(ordinal)
  const ti = resolveWordIndex(wordOrdinals, clamped, clamped >= ordinal)

  const span = MAX_PHRASE_WORDS - 1
  const li = ti > ai ? Math.min(ti, ai + span) : Math.max(ti, ai - span)

  const fromIdx = Math.min(ai, li)
  const toIdx = Math.max(ai, li)
  return {
    from: wordOrdinals[fromIdx] ?? ordinal,
    to: wordOrdinals[toIdx] ?? ordinal,
  }
}

function ordinalFromEvent(e: { target: EventTarget | null }): number | null {
  const el = (e.target as HTMLElement | null)?.closest?.('[data-ordinal]')
  if (!el) return null
  const value = Number((el as HTMLElement).dataset.ordinal)
  return Number.isFinite(value) ? value : null
}

export function usePhraseSelection({ enabled, sentences, onSelect }: Params) {
  const [dragRange, setDragRange] = useState<DragRange | null>(null)
  const [dragging, setDragging] = useState(false)
  const anchorRef = useRef<Anchor | null>(null)
  const suppressClickRef = useRef(false)

  const reset = useCallback(() => {
    anchorRef.current = null
    setDragRange(null)
    setDragging(false)
  }, [])

  // Завершает drag: если якорь ещё жив и диапазон покрывает >=2 слова,
  // сообщаем о выборе фразы. Идемпотентно — после reset() anchorRef.current
  // становится null, поэтому повторный вызов (container -> window) безопасен.
  const finalize = useCallback(() => {
    const anchor = anchorRef.current
    if (enabled && anchor && dragging && dragRange && dragRange.to > dragRange.from) {
      suppressClickRef.current = true
      onSelect(dragRange, anchor.sentence)
    }
    reset()
  }, [enabled, dragging, dragRange, onSelect, reset])

  const finalizeRef = useRef(finalize)
  finalizeRef.current = finalize

  useEffect(() => {
    if (!dragging) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') reset()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [dragging, reset])

  // Fallback на случай, если pointerup/pointercancel происходит за пределами
  // контейнера (курсор ушёл с окна) — иначе drag застревает навсегда.
  useEffect(() => {
    if (!dragging) return
    const onWindowPointerUp = () => finalizeRef.current()
    window.addEventListener('pointerup', onWindowPointerUp)
    window.addEventListener('pointercancel', reset)
    return () => {
      window.removeEventListener('pointerup', onWindowPointerUp)
      window.removeEventListener('pointercancel', reset)
    }
  }, [dragging, reset])

  // Если фича выключается прямо во время drag — сбрасываем состояние, чтобы
  // не остаться с "подвисшим" выделением.
  useEffect(() => {
    if (!enabled) reset()
  }, [enabled, reset])

  const onPointerDown: PointerEventHandler = (e) => {
    // Флаг мог остаться выставленным, если предыдущий finalize отработал
    // через window-фоллбек за пределами контейнера — click тогда никогда не
    // приходит, и флаг некому сбросить. Чистим его на каждом новом нажатии.
    suppressClickRef.current = false
    if (!enabled || e.pointerType !== 'mouse' || e.button !== 0) return
    const ordinal = ordinalFromEvent(e)
    if (ordinal === null) return
    const sentence = sentences.find((s) =>
      s.tokens.some((tok) => isWord(tok) && tok.i === ordinal),
    )
    if (!sentence) return
    const wordOrdinals = sentence.tokens.filter(isWord).map((word) => word.i)
    anchorRef.current = {
      ordinal,
      sentence,
      wordOrdinals,
    }
  }

  const onPointerOver: PointerEventHandler = (e) => {
    if (!enabled) return
    const anchor = anchorRef.current
    if (!anchor) return
    // Кнопка могла быть отпущена за пределами контейнера ещё до старта drag
    // (dragging === false, window-фоллбек не подключён) — якорь тогда
    // выживает, и hover без нажатой кнопки запустил бы фантомный drag.
    if (e.buttons !== 1) return
    const ordinal = ordinalFromEvent(e)
    if (ordinal === null) return
    if (!dragging && ordinal === anchor.ordinal) return
    setDragging(true)
    setDragRange(clampRange(anchor, ordinal))
  }

  const onPointerUp: PointerEventHandler = () => {
    finalize()
  }

  // Предотвращаем нативное выделение текста при drag от слова (click при
  // этом сохраняется). Copy-paste произвольного текста из ридера в v1
  // приносим в жертву механике фраз.
  const onMouseDown: MouseEventHandler = (e) => {
    if (!enabled || e.button !== 0) return
    if (ordinalFromEvent(e) !== null) e.preventDefault()
  }

  // Гасим click, синтезируемый браузером после pointerup, завершившего drag,
  // иначе поверх карточки фразы откроется карточка слова.
  const onClickCapture: MouseEventHandler = (e) => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false
      e.preventDefault()
      e.stopPropagation()
    }
  }

  return {
    dragRange: dragging ? dragRange : null,
    containerProps: {
      onPointerDown,
      onPointerOver,
      onPointerUp,
      onPointerCancel: reset,
      onMouseDown,
      onClickCapture,
      style: dragging ? ({ userSelect: 'none' } as const) : undefined,
    },
  }
}
