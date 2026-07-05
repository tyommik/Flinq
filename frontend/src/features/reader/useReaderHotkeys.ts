import { useEffect } from 'react'

interface Params {
  enabled: boolean
  onPrev: () => void
  onNext: () => void
  onToggleMode: () => void
  onEscape: () => void
  onUndo?: () => void
  onToggleFont?: () => void
  onToggleSidebar?: () => void
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable
}

export function useReaderHotkeys({
  enabled,
  onPrev,
  onNext,
  onToggleMode,
  onEscape,
  onUndo,
  onToggleFont,
  onToggleSidebar,
}: Params) {
  useEffect(() => {
    if (!enabled) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return

      if (event.key === 'ArrowLeft') {
        event.preventDefault()
        onPrev()
        return
      }
      if (event.key === 'ArrowRight') {
        event.preventDefault()
        onNext()
        return
      }
      if (event.key === 'Escape') {
        onEscape()
        return
      }

      const isUndoCombo =
        (event.ctrlKey || event.metaKey) &&
        !event.altKey &&
        !event.shiftKey &&
        event.key.toLowerCase() === 'z'
      // Only preventDefault/consume the combo when an undo will actually run —
      // otherwise the browser's native undo (e.g. in a text field elsewhere) is
      // silently swallowed for nothing.
      if (isUndoCombo && onUndo) {
        event.preventDefault()
        onUndo()
        return
      }

      // Letter shortcuts require no modifier keys at all.
      if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return

      const key = event.key.toLowerCase()
      if (key === 'm') {
        onToggleMode()
        return
      }
      if (key === 'f' && onToggleFont) {
        onToggleFont()
        return
      }
      if (key === 's' && onToggleSidebar) {
        onToggleSidebar()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled, onPrev, onNext, onToggleMode, onEscape, onUndo, onToggleFont, onToggleSidebar])
}
