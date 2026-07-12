import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, ChevronDown, ChevronUp } from 'lucide-react'

import { useWordLookup, useWordCardMutations } from './useWordCard'
import { TranslationFields } from './TranslationFields'
import { useReaderStore } from './readerStore'
import { dictionaryApi } from '@/api/dictionary'
import { aiApi } from '@/api/ai'
import { ApiError } from '@/api/client'
import { ConfidencePicker } from '@/components/ConfidencePicker'
import type { SelectedItem } from './selectedItem'

interface Props {
  word: SelectedItem | null
  lang: string
  target: string
  lessonId: string | null
  onClose: () => void
  sentenceText: string | null
}

export function WordCard({ word, lang, target, lessonId, onClose, sentenceText }: Props) {
  const expanded = useReaderStore((s) => s.wordCardExpanded)
  const setExpanded = useReaderStore((s) => s.setWordCardExpanded)
  const kind = word?.kind ?? 'token'
  const text = word?.n ?? null
  const lookup = useWordLookup(lang, text, target, kind)
  const m = useWordCardMutations({ kind, lang, text: text ?? '', target, lessonId })

  const data = lookup.data
  const itemId = data?.item_id ?? null
  const status = data?.status ?? 'new'
  const confidence = data?.confidence ?? null

  // MUST be memoized: TranslationFields resets its per-field drafts when the
  // `translations` prop identity changes, so a fresh `.filter()` array on
  // every render would wipe the user's typing mid-edit.
  const variants = useMemo(
    () => (data?.translations.all ?? []).filter((t) => t.target_language_code === target),
    [data, target],
  )

  // AI suggestion for `new` and `known` words (needs lesson context; guarded).
  // Gate on `data?.status` directly (not the defaulted `status` above) so we
  // never fire the AI query before the lookup has told us the real status —
  // `status` defaults to 'new' pre-lookup, which would otherwise race an
  // AI call for a word that turns out to be tracked/ignored.
  const wantAi = data?.status === 'new' || data?.status === 'known'
  const aiContext = word?.sentenceText ?? sentenceText ?? word?.t ?? ''
  const dict = useQuery({
    queryKey: ['dict', lang, target, text ?? ''],
    queryFn: () => dictionaryApi.lookup(lang, target, text as string),
    enabled: text !== null && kind === 'token',
  })
  const ai = useQuery({
    queryKey: ['ai-hint', lang, target, text ?? '', aiContext],
    queryFn: () => aiApi.translate({
      surface_text: word!.t, context_text: aiContext,
      target_language_code: target, lesson_id: lessonId ?? undefined,
    }),
    enabled: text !== null && wantAi,
    retry: false,
  })
  const aiDisabled = ai.error instanceof ApiError && ai.error.status === 503

  const [saveError, setSaveError] = useState(false)

  const [tagDraft, setTagDraft] = useState('')
  const [noteDraft, setNoteDraft] = useState('')
  const noteSavedRef = useRef<string>('')
  useEffect(() => {
    const n = data?.note ?? ''
    setNoteDraft(n)
    noteSavedRef.current = n
  }, [data?.item_id, data?.note])

  async function saveNote() {
    const value = noteDraft
    if (value === noteSavedRef.current) return
    const prev = noteSavedRef.current
    noteSavedRef.current = value
    try {
      await withItem((id) => m.saveNote.mutateAsync({ itemId: id, note: value }))
      setSaveError(false)
    } catch {
      noteSavedRef.current = prev
      setSaveError(true)
    }
  }

  useEffect(() => {
    if (!word) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      const target = e.target as HTMLElement | null
      const isEditableTarget =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target?.isContentEditable
      if (isEditableTarget) return
      if (data && /^[1-4]$/.test(e.key)) applyStatus('tracked', Number(e.key))
      if (data && e.key === 'k') applyStatus('known', null)
      if (data && e.key === 'i') applyStatus('ignored', null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [word, data])

  if (!word) return null

  async function ensureItem(nextStatus: 'tracked' | 'known' | 'ignored', conf: number | null) {
    const res = await m.setStatus.mutateAsync({ itemId, status: nextStatus, confidence: conf })
    return res.item_id
  }

  function applyStatus(nextStatus: 'tracked' | 'known' | 'ignored', conf: number | null) {
    void m.setStatus.mutate({ itemId, status: nextStatus, confidence: conf })
  }

  async function withItem(fn: (id: string) => Promise<unknown>): Promise<void> {
    const id = itemId ?? (await ensureItem('tracked', 0))
    await fn(id)
  }

  type Suggestion = { text: string; badge: '✦' | '📘'; source: 'ai' | 'dictionary' }
  const suggestions: Suggestion[] = [
    ...(ai.data?.hints ?? []).map((h) => ({ text: h.text, badge: '✦' as const, source: 'ai' as const })),
    ...(dict.data?.entries ?? []).flatMap((e) =>
      e.senses.map((s) => ({ text: s.translation, badge: '📘' as const, source: 'dictionary' as const })),
    ),
  ]
  const visibleSuggestions = expanded ? suggestions : suggestions.slice(0, 2)
  const isIgnored = data?.status === 'ignored'

  return (
    <>
      <div
        data-testid="word-card-backdrop"
        className="fixed inset-0 z-[var(--z-modal-backdrop)] bg-black/10 md:hidden"
        onClick={onClose}
      />
      <div
        data-testid="word-card"
        className="fixed inset-x-0 bottom-0 z-[var(--z-modal)] rounded-t-xl border border-border bg-card p-4 shadow-lg md:inset-x-auto md:right-0 md:top-16 md:h-[calc(100vh-4rem)] md:w-80 md:overflow-y-auto md:rounded-none md:border-y-0 md:border-r-0 md:border-l md:shadow-none"
      >
        <button
          type="button" aria-label="Закрыть" onClick={onClose}
          className="absolute right-3 top-3 rounded-md p-1 hover:bg-accent"
        >
          <X className="h-4 w-4" />
        </button>

        <p className="text-2xl font-semibold">{word.t}</p>

        {!isIgnored && (
          <>
            {/* Saved translation */}
            <label className="mt-4 block text-sm font-medium">Перевод</label>
            <TranslationFields
              translations={variants}
              onCreate={(value) => withItem((id) =>
                m.saveTranslation.mutateAsync({ itemId: id, text: value, source: 'user' }))}
              onUpdate={(translationId, value) => withItem((id) =>
                m.updateTranslation.mutateAsync({ itemId: id, translationId, text: value }))}
              onDelete={(translationId) => withItem((id) =>
                m.deleteTranslation.mutateAsync({ itemId: id, translationId }))}
            />

            <div data-testid="word-card-suggestions" className="mt-4">
              {visibleSuggestions.length > 0 && <p className="text-sm font-medium">Подсказки</p>}
              <ul className="mt-1 space-y-1">
                {visibleSuggestions.map((sug, idx) => (
                  <li key={`${sug.source}-${idx}`}
                      className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-sm">
                    <span className="text-primary">
                      {sug.text}<span className="ml-2 text-muted-foreground">{sug.badge}</span>
                    </span>
                    <button
                      type="button" aria-label={`Добавить перевод (${sug.badge}): ${sug.text}`}
                      onClick={() => void withItem((id) =>
                        m.saveTranslation.mutateAsync({ itemId: id, text: sug.text, source: sug.source }))}
                      className="rounded p-1 hover:bg-accent"
                    >+</button>
                  </li>
                ))}
              </ul>
              {aiDisabled && (
                <p className="mt-1 text-sm text-muted-foreground">AI-переводы отключены</p>
              )}
              {ai.isError && !aiDisabled && (
                <p className="mt-1 text-sm text-destructive">
                  Не удалось получить AI-перевод{' '}
                  <button
                    type="button"
                    onClick={() => void ai.refetch()}
                    className="underline"
                  >
                    Повторить
                  </button>
                </p>
              )}
            </div>
          </>
        )}

        {isIgnored && (
          <div data-testid="word-card-ignored" className="mt-4">
            <p className="text-sm font-medium">Игнорируется</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Выберите уровень 1–4 или ✓, чтобы вернуть слово в изучение
            </p>
          </div>
        )}

        {expanded && !isIgnored && (
          <div data-testid="word-card-expanded" className="mt-4 space-y-4">
            <div>
              <p className="text-sm font-medium">Теги</p>
              <div className="mt-1 flex flex-wrap gap-2">
                {(data?.tags ?? []).map((tag) => (
                  <button key={tag} type="button"
                    onClick={() => itemId && m.removeTag.mutate({ itemId, tag })}
                    className="rounded-full border border-border px-2 py-0.5 text-xs hover:bg-accent">
                    {tag} ✕
                  </button>
                ))}
                <input
                  className="min-w-24 flex-1 rounded-md border border-border px-2 py-0.5 text-xs"
                  placeholder="Тег+"
                  value={tagDraft}
                  onChange={(e) => setTagDraft(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key === 'Enter' && tagDraft.trim()) {
                      await withItem((id) => m.addTag.mutateAsync({ itemId: id, tag: tagDraft.trim() }))
                      setTagDraft('')
                    }
                  }}
                />
              </div>
            </div>
            <div>
              <p className="text-sm font-medium">Заметки</p>
              <textarea
                className="mt-1 w-full rounded-md border border-border px-3 py-2 text-sm"
                rows={3}
                value={noteDraft}
                onChange={(e) => setNoteDraft(e.target.value)}
                onBlur={() => void saveNote()}
              />
              {saveError && <p className="mt-1 text-sm text-destructive">Не удалось сохранить</p>}
            </div>
          </div>
        )}

        {/* Footer: 🗑 [1][2][3][4] ✓ — gated on the lookup having loaded, so a
            click always sees the real item id/status (never a stale "new word"
            default while the lookup is still in flight). */}
        {data && (
          <div className="mt-4 border-t border-border pt-3">
            <ConfidencePicker
              status={status}
              confidence={confidence}
              onSelect={(s, c) => applyStatus(s, c)}
            />
          </div>
        )}

        {!isIgnored && (
          <button
            type="button"
            aria-label={expanded ? 'Свернуть' : 'Развернуть'}
            onClick={() => setExpanded(!expanded)}
            className="mx-auto mt-2 flex rounded-md p-1 text-muted-foreground hover:bg-accent"
          >
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
        )}
      </div>
    </>
  )
}
