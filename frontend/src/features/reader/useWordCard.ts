import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { vocabularyApi } from '@/api/vocabulary'
import type { ItemKind, WriteStatus } from '@/api/vocabulary'

export function wordLookupKey(lang: string, text: string, target: string) {
  return ['word-card', lang, text, target] as const
}

export function useWordLookup(lang: string, text: string | null, target: string) {
  return useQuery({
    queryKey: wordLookupKey(lang, text ?? '', target),
    queryFn: () => vocabularyApi.lookup(lang, text as string, target),
    enabled: text !== null,
  })
}

/**
 * Mutations for the open card. `invalidate()` refreshes both the card lookup
 * and the reader token statuses so highlight colours update.
 */
export function useWordCardMutations(opts: {
  lang: string
  text: string
  target: string
  lessonId: string
}) {
  const qc = useQueryClient()
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: wordLookupKey(opts.lang, opts.text, opts.target) })
    void qc.invalidateQueries({ queryKey: ['reader-statuses', opts.lessonId] })
  }

  const setStatus = useMutation({
    // For a new word (no id) pass itemId=null → create; else patch.
    mutationFn: (v: { itemId: string | null; status: WriteStatus; confidence: number | null }) =>
      v.itemId === null
        ? vocabularyApi.createItem({
            kind: 'token', language_code: opts.lang, text: opts.text,
            status: v.status, confidence: v.confidence,
          })
        : vocabularyApi.patchItem('token', v.itemId, { status: v.status, confidence: v.confidence }),
    onSuccess: invalidate,
  })

  const saveTranslation = useMutation({
    mutationFn: (v: { itemId: string; text: string; source?: 'user' | 'ai' | 'dictionary' }) =>
      vocabularyApi.addTranslation('token' as ItemKind, v.itemId, {
        target_language_code: opts.target, translation_text: v.text,
        is_primary: true, source_type: v.source ?? 'user',
      }),
    onSuccess: invalidate,
  })

  const saveNote = useMutation({
    mutationFn: (v: { itemId: string; note: string }) =>
      vocabularyApi.putNote('token', v.itemId, v.note),
    onSuccess: invalidate,
  })

  const addTag = useMutation({
    mutationFn: (v: { itemId: string; tag: string }) => vocabularyApi.addTag('token', v.itemId, v.tag),
    onSuccess: invalidate,
  })

  const removeTag = useMutation({
    mutationFn: (v: { itemId: string; tag: string }) => vocabularyApi.removeTag('token', v.itemId, v.tag),
    onSuccess: invalidate,
  })

  return { setStatus, saveTranslation, saveNote, addTag, removeTag }
}
