import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { vocabularyApi } from '@/api/vocabulary'
import type { ItemKind, WriteStatus } from '@/api/vocabulary'

export function wordLookupKey(kind: ItemKind, lang: string, text: string, target: string) {
  return ['word-card', kind, lang, text, target] as const
}

export function useWordLookup(lang: string, text: string | null, target: string, kind: ItemKind) {
  return useQuery({
    queryKey: wordLookupKey(kind, lang, text ?? '', target),
    queryFn: () => vocabularyApi.lookup(lang, text as string, target, kind),
    enabled: text !== null,
  })
}

/**
 * Mutations for the open card. `invalidate()` refreshes the card lookup, the
 * reader token statuses and (for phrases) the reader phrase list.
 */
export function useWordCardMutations(opts: {
  kind: ItemKind
  lang: string
  text: string
  /** Surface form (as shown to the user) to persist as display_text on
      create. `text` above is the normalized join key used for lookups and
      cache invalidation — it must not be sent as the item's display text,
      or phrases lose their punctuation/casing (e.g. "so far so good"
      instead of "So far, so good"). */
  surfaceText: string
  target: string
  lessonId: string | null
}) {
  const qc = useQueryClient()
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: wordLookupKey(opts.kind, opts.lang, opts.text, opts.target) })
    if (opts.kind === 'phrase') {
      void qc.invalidateQueries({ queryKey: ['phrases', opts.lang] })
    }
    if (opts.lessonId !== null) {
      void qc.invalidateQueries({ queryKey: ['reader-statuses', opts.lessonId] })
    }
  }

  const setStatus = useMutation({
    // For a new item (no id) pass itemId=null → create; else patch.
    mutationFn: (v: { itemId: string | null; status: WriteStatus; confidence: number | null }) =>
      v.itemId === null
        ? vocabularyApi.createItem({
            kind: opts.kind, language_code: opts.lang, text: opts.surfaceText,
            status: v.status, confidence: v.confidence,
          })
        : vocabularyApi.patchItem(opts.kind, v.itemId, { status: v.status, confidence: v.confidence }),
    onSuccess: invalidate,
  })

  const saveTranslation = useMutation({
    mutationFn: (v: { itemId: string; text: string; source?: 'user' | 'ai' | 'dictionary' }) =>
      vocabularyApi.addTranslation(opts.kind, v.itemId, {
        target_language_code: opts.target, translation_text: v.text,
        source_type: v.source ?? 'user',
      }),
    onSuccess: invalidate,
  })

  const updateTranslation = useMutation({
    mutationFn: (v: { itemId: string; translationId: string; text: string }) =>
      vocabularyApi.updateTranslation(opts.kind, v.itemId, v.translationId, v.text),
    onSuccess: invalidate,
  })

  const deleteTranslation = useMutation({
    mutationFn: (v: { itemId: string; translationId: string }) =>
      vocabularyApi.deleteTranslation(opts.kind, v.itemId, v.translationId),
    onSuccess: invalidate,
  })

  const saveNote = useMutation({
    mutationFn: (v: { itemId: string; note: string }) =>
      vocabularyApi.putNote(opts.kind, v.itemId, v.note),
    onSuccess: invalidate,
  })

  const addTag = useMutation({
    mutationFn: (v: { itemId: string; tag: string }) => vocabularyApi.addTag(opts.kind, v.itemId, v.tag),
    onSuccess: invalidate,
  })

  const removeTag = useMutation({
    mutationFn: (v: { itemId: string; tag: string }) => vocabularyApi.removeTag(opts.kind, v.itemId, v.tag),
    onSuccess: invalidate,
  })

  return { setStatus, saveTranslation, updateTranslation, deleteTranslation, saveNote, addTag, removeTag }
}
