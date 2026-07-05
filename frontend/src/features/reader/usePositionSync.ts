import { useEffect, useRef } from 'react'

import type { ReaderPosition } from '@/api/reader'

import type { ViewMode } from './readerStore'
import { usePutPosition } from './useReaderQueries'

interface Params {
  lessonId: string
  mode: ViewMode
  currentSegmentId: string | null
  currentOrdinal: number | null
  enabled: boolean
}

const DEBOUNCE_MS = 2000

type PositionPayload = { lesson_id: string } & ReaderPosition

export function usePositionSync({
  lessonId,
  mode,
  currentSegmentId,
  currentOrdinal,
  enabled,
}: Params) {
  const { mutate } = usePutPosition()
  const mutateRef = useRef(mutate)
  mutateRef.current = mutate

  const timerRef = useRef<number | null>(null)
  const pendingRef = useRef<PositionPayload | null>(null)

  useEffect(() => {
    if (!enabled) return

    const payload: PositionPayload = {
      lesson_id: lessonId,
      view_mode: mode,
      current_segment_id: currentSegmentId,
      current_token_ordinal: currentOrdinal,
    }
    pendingRef.current = payload

    if (timerRef.current != null) window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      pendingRef.current = null
      mutateRef.current(payload)
    }, DEBOUNCE_MS)

    return () => {
      if (timerRef.current != null) {
        window.clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [enabled, lessonId, mode, currentSegmentId, currentOrdinal])

  // Flush any pending update immediately on unmount rather than losing it.
  // NOTE: this must NOT gate on timerRef — effect cleanups run in declaration
  // order on unmount, so the debounce effect's cleanup (above) has already
  // cleared timerRef.current by the time this runs. pendingRef is the sole
  // source of truth for "is there an unsent update".
  useEffect(() => {
    return () => {
      if (pendingRef.current) {
        mutateRef.current(pendingRef.current)
        pendingRef.current = null
      }
    }
  }, [])
}
