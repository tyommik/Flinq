import { useRef } from 'react'
import type { TouchEvent } from 'react'

const SWIPE_THRESHOLD_PX = 60

interface Params {
  onSwipeLeft: () => void
  onSwipeRight: () => void
}

export function useSwipe({ onSwipeLeft, onSwipeRight }: Params) {
  const startXRef = useRef<number | null>(null)

  const onTouchStart = (event: TouchEvent) => {
    startXRef.current = event.touches[0]?.clientX ?? null
  }

  const onTouchEnd = (event: TouchEvent) => {
    const startX = startXRef.current
    startXRef.current = null
    if (startX == null) return

    const endX = event.changedTouches[0]?.clientX ?? startX
    const deltaX = endX - startX

    if (deltaX <= -SWIPE_THRESHOLD_PX) {
      onSwipeLeft()
    } else if (deltaX >= SWIPE_THRESHOLD_PX) {
      onSwipeRight()
    }
  }

  return { onTouchStart, onTouchEnd }
}
