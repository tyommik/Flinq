import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, ChevronDown, ChevronUp, Check, Trash2 } from 'lucide-react'

import { useWordLookup, useWordCardMutations } from './useWordCard'
import { dictionaryApi } from '@/api/dictionary'
import { aiApi } from '@/api/ai'

interface SelectedWord {
  t: string
  n: string
  i: number
}

interface Props {
  word: SelectedWord | null
  lang: string
  target: string
  lessonId: string
  onClose: () => void
}

const PILLS = [1, 2, 3, 4] as const

export function WordCard({ word, lang, target, lessonId, onClose }: Props) {
  const [expanded, setExpanded] = useState(false)
  const text = word?.n ?? null
  const lookup = useWordLookup(lang, text, target)
  const m = useWordCardMutations({ lang, text: text ?? '', target, lessonId })

  const data = lookup.data
  const itemId = data?.item_id ?? null
  const status = data?.status ?? 'new'
  const confidence = data?.confidence ?? null

  // AI suggestion only for `new` words (needs lesson context; guarded).
  // Gate on `data?.status` directly (not the defaulted `status` above) so we
  // never fire the AI query before the lookup has told us the real status —
  // `status` defaults to 'new' pre-lookup, which would otherwise race an
  // AI call for a word that turns out to be tracked/known/ignored.
  const wantAi = data?.status === 'new'
  const dict = useQuery({
    queryKey: ['dict', lang, target, text ?? ''],
    queryFn: () => dictionaryApi.lookup(lang, target, text as string),
    enabled: text !== null,
  })
  const ai = useQuery({
    queryKey: ['ai-hint', lang, target, text ?? ''],
    queryFn: () => aiApi.translate({
      surface_text: word!.t, context_text: word!.t,
      target_language_code: target, lesson_id: lessonId,
    }),
    enabled: text !== null && wantAi,
    retry: false,
  })

  // translation input (debounced save on change + save on blur)
  const [draft, setDraft] = useState('')
  const savedRef = useRef<string>('')
  const [saveError, setSaveError] = useState(false)
  // Tracks whether the user has started editing the current word's translation,
  // so an in-flight lookup that resolves *after* the user started typing never
  // clobbers their unsaved input.
  const dirtyRef = useRef(false)

  // New word selected: reset local editing state before the fresh lookup lands.
  useEffect(() => {
    dirtyRef.current = false
    setDraft('')
    savedRef.current = ''
  }, [text])

  // Populate the draft from the server once lookup data is available — unless
  // the user already started editing this word's translation.
  useEffect(() => {
    if (!data || dirtyRef.current) return
    const primary = data.translations.primary?.text ?? ''
    setDraft(primary)
    savedRef.current = primary
  }, [data, text])

  useEffect(() => {
    if (!word) return
    const value = draft.trim()
    if (!value || value === savedRef.current) return
    const timer = setTimeout(() => { void saveTranslation() }, 800)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft])

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
      const id = itemId ?? (await ensureItem('tracked', 0))
      await m.saveNote.mutateAsync({ itemId: id, note: value })
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

  async function saveTranslation() {
    const value = draft.trim()
    if (!value || value === savedRef.current) return
    const prev = savedRef.current
    savedRef.current = value
    try {
      // new word: create tracked/0 first, then translate
      const id = itemId ?? (await ensureItem('tracked', 0))
      await m.saveTranslation.mutateAsync({ itemId: id, text: value, source: 'user' })
      setSaveError(false)
    } catch {
      savedRef.current = prev
      setSaveError(true)
    }
  }

  type Suggestion = { text: string; badge: '' | '✦' | '📘'; source: 'user' | 'ai' | 'dictionary' }
  const suggestions: Suggestion[] = [
    ...(data?.translations.all ?? []).map((t) => ({ text: t.text, badge: '' as const, source: 'user' as const })),
    ...(ai.data?.hints ?? []).map((h) => ({ text: h.text, badge: '✦' as const, source: 'ai' as const })),
    ...(dict.data?.entries ?? []).flatMap((e) =>
      e.senses.map((s) => ({ text: s.translation, badge: '📘' as const, source: 'dictionary' as const })),
    ),
  ]

  async function saveSuggestion(sug: Suggestion) {
    const id = itemId ?? (await ensureItem('tracked', 0))
    await m.saveTranslation.mutateAsync({ itemId: id, text: sug.text, source: sug.source })
  }

  return (
    <>
      <div
        data-testid="word-card-backdrop"
        className="fixed inset-0 z-[var(--z-modal-backdrop)] bg-black/10 md:hidden"
        onClick={onClose}
      />
      <div
        data-testid="word-card"
        className="fixed inset-x-0 bottom-0 z-[var(--z-modal)] rounded-t-xl border border-border bg-card p-4 shadow-lg md:inset-x-auto md:right-0 md:top-0 md:h-full md:w-80 md:overflow-y-auto md:rounded-none md:border-y-0 md:border-r-0 md:border-l md:shadow-none"
      >
        <button
          type="button" aria-label="Закрыть" onClick={onClose}
          className="absolute right-3 top-3 rounded-md p-1 hover:bg-accent"
        >
          <X className="h-4 w-4" />
        </button>

        <p className="text-2xl font-semibold">{word.t}</p>

        {/* Saved translation */}
        <label className="mt-4 block text-sm font-medium">Сохранённый перевод</label>
        <input
          className="mt-1 w-full rounded-md border border-border px-3 py-2 text-base"
          placeholder="Введите новый перевод здесь"
          value={draft}
          onChange={(e) => { dirtyRef.current = true; setDraft(e.target.value) }}
          onBlur={() => void saveTranslation()}
          onKeyDown={(e) => { if (e.key === 'Enter') void saveTranslation() }}
        />
        {saveError && <p className="mt-1 text-sm text-destructive">Не удалось сохранить</p>}

        <div data-testid="word-card-suggestions" className="mt-4">
          {suggestions.length > 0 && <p className="text-sm font-medium">Популярные переводы</p>}
          <ul className="mt-1 space-y-1">
            {suggestions.map((sug, idx) => (
              <li key={`${sug.source}-${idx}`}
                  className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-sm">
                <span className="text-primary">
                  {sug.text}{sug.badge && <span className="ml-2 text-muted-foreground">{sug.badge}</span>}
                </span>
                <button
                  type="button" aria-label={`Добавить перевод: ${sug.text}`}
                  onClick={() => void saveSuggestion(sug)}
                  className="rounded p-1 hover:bg-accent"
                >+</button>
              </li>
            ))}
          </ul>
          {ai.isError && <p className="mt-1 text-sm text-destructive">Не удалось получить AI-перевод</p>}
        </div>

        {expanded && (
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
                      const id = itemId ?? (await ensureItem('tracked', 0))
                      await m.addTag.mutateAsync({ itemId: id, tag: tagDraft.trim() })
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
            </div>
          </div>
        )}

        {/* Footer: 🗑 [1][2][3][4] ✓ — gated on the lookup having loaded, so a
            click always sees the real item id/status (never a stale "new word"
            default while the lookup is still in flight). */}
        {data && (
          <div className="mt-4 flex items-center justify-between border-t border-border pt-3">
            <button
              type="button" aria-label="Игнорировать" title="Игнорировать"
              onClick={() => applyStatus('ignored', null)}
              className={`rounded-full border p-2 hover:bg-accent ${status === 'ignored' ? 'border-foreground' : 'border-border'}`}
            >
              <Trash2 className="h-4 w-4" />
            </button>
            <div className="flex items-center gap-1">
              {PILLS.map((n) => (
                <button
                  key={n} type="button" aria-label={`Уровень ${n}`}
                  onClick={() => applyStatus('tracked', n)}
                  className={`flex h-8 w-8 items-center justify-center rounded-full border text-sm ${
                    status === 'tracked' && confidence === n
                      ? 'border-primary bg-primary/10 font-semibold'
                      : 'border-border hover:bg-accent'
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
            <button
              type="button" aria-label="Изучено" title="Изучено"
              onClick={() => applyStatus('known', null)}
              className={`rounded-full border p-2 hover:bg-accent ${status === 'known' ? 'border-primary bg-primary/10' : 'border-border'}`}
            >
              <Check className="h-4 w-4" />
            </button>
          </div>
        )}

        <button
          type="button"
          aria-label={expanded ? 'Свернуть' : 'Развернуть'}
          onClick={() => setExpanded((v) => !v)}
          className="mx-auto mt-2 flex rounded-md p-1 text-muted-foreground hover:bg-accent"
        >
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
      </div>
    </>
  )
}
