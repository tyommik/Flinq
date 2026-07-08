import { useEffect, useRef, useState } from 'react'
import { Plus, X } from 'lucide-react'

import { ApiError } from '@/api/client'
import type { TranslationOut } from '@/api/vocabulary'

interface Props {
  /** Variants for the current target language, creation order (primary first). */
  translations: TranslationOut[]
  onCreate: (text: string) => Promise<void>
  onUpdate: (translationId: string, text: string) => Promise<void>
  onDelete: (translationId: string) => Promise<void>
}

/**
 * Translation variants as a list of inputs (spec §2.1): Enter/blur saves,
 * emptying a field deletes the variant, hover shows +/✕, a single empty
 * field is always present when there are no variants.
 */
export function TranslationFields({ translations, onCreate, onUpdate, onDelete }: Props) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  // null = no pending new field; '' or text = the single pending field's draft.
  const [newDraft, setNewDraft] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  // Guards against the double-fire from Enter (onKeyDown) immediately followed
  // by blur before the first commit's promise has settled: keyed per field so
  // a second commit for the SAME field is skipped while the first is pending.
  const inFlightRef = useRef<Set<string>>(new Set())

  // Server list changed (a save/delete landed): reset local drafts so fields
  // re-sync to server values. Any other field's uncommitted draft is
  // intentionally dropped — the list refresh re-renders from server state.
  useEffect(() => {
    setDrafts({})
  }, [translations])

  const showAlwaysEmpty = translations.length === 0
  const pendingOpen = newDraft !== null || showAlwaysEmpty
  const pendingValue = newDraft ?? ''

  async function run(action: () => Promise<void>) {
    try {
      await action()
      setSaveError(null)
      return true
    } catch (err) {
      setSaveError(
        err instanceof ApiError && err.status === 409
          ? 'Такой вариант уже есть'
          : 'Не удалось сохранить',
      )
      return false
    }
  }

  async function commitExisting(t: TranslationOut) {
    const draft = drafts[t.id]
    if (draft === undefined) return
    const value = draft.trim()
    if (value === t.text) return
    if (inFlightRef.current.has(t.id)) return
    inFlightRef.current.add(t.id)
    try {
      if (value === '') {
        await run(() => onDelete(t.id))
        return
      }
      await run(() => onUpdate(t.id, value))
    } finally {
      inFlightRef.current.delete(t.id)
    }
  }

  async function commitNew() {
    const value = pendingValue.trim()
    if (value === '') {
      if (!showAlwaysEmpty) setNewDraft(null)
      return
    }
    if (inFlightRef.current.has('new')) return
    inFlightRef.current.add('new')
    try {
      if (await run(() => onCreate(value))) setNewDraft(null)
    } finally {
      inFlightRef.current.delete('new')
    }
  }

  function openNewField() {
    setNewDraft((v) => v ?? '')
  }

  return (
    <div data-testid="translation-fields" className="mt-1 space-y-2">
      {translations.map((t) => (
        <div key={t.id} className="group relative">
          <input
            className="w-full rounded-md border border-border px-3 py-2 pr-16 text-base"
            value={drafts[t.id] ?? t.text}
            onChange={(e) => setDrafts((d) => ({ ...d, [t.id]: e.target.value }))}
            onBlur={() => void commitExisting(t)}
            onKeyDown={(e) => { if (e.key === 'Enter') void commitExisting(t) }}
          />
          <span className="absolute inset-y-0 right-2 hidden items-center gap-1 group-focus-within:flex group-hover:flex">
            <button
              type="button" aria-label="Добавить вариант"
              onClick={openNewField}
              className="rounded p-1 text-muted-foreground hover:bg-accent"
            >
              <Plus className="h-4 w-4" />
            </button>
            <button
              type="button" aria-label={`Удалить вариант: ${t.text}`}
              onClick={() => void run(() => onDelete(t.id))}
              className="rounded p-1 text-muted-foreground hover:bg-accent"
            >
              <X className="h-4 w-4" />
            </button>
          </span>
        </div>
      ))}
      {pendingOpen && (
        <input
          // autoFocus: the field appears on explicit "+" click, not on page load.
          autoFocus={newDraft !== null}
          className="w-full rounded-md border border-border px-3 py-2 text-base"
          placeholder="Введите новый перевод здесь"
          value={pendingValue}
          onChange={(e) => setNewDraft(e.target.value)}
          onBlur={() => void commitNew()}
          onKeyDown={(e) => { if (e.key === 'Enter') void commitNew() }}
        />
      )}
      {saveError && <p className="text-sm text-destructive">{saveError}</p>}
    </div>
  )
}
