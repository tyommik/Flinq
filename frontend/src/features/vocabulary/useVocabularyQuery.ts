import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { vocabularyApi } from '@/api/vocabulary'
import type { ItemKind, VocabListParams } from '@/api/vocabulary'

export const VOCAB_TARGET = 'ru'

export function vocabListKey(params: VocabListParams) {
  return ['vocab-list', params] as const
}

export function useVocabList(params: VocabListParams, enabled = true) {
  return useQuery({
    queryKey: vocabListKey(params),
    queryFn: () => vocabularyApi.list(params),
    enabled,
    placeholderData: (prev) => prev,
  })
}

export function useVocabInvalidate() {
  const qc = useQueryClient()
  return () => void qc.invalidateQueries({ queryKey: ['vocab-list'] })
}

export function useBulkAction() {
  const qc = useQueryClient()
  const invalidate = useVocabInvalidate()
  return useMutation({
    mutationFn: vocabularyApi.bulk,
    onSuccess: () => {
      invalidate()
      // Bulk actions (set_known/set_ignored/delete) can change or remove
      // phrases; an open reader keeps highlighting stale phrase state until
      // staleTime unless we invalidate its cache too. Prefix-invalidate
      // across all languages — cheap and correct.
      void qc.invalidateQueries({ queryKey: ['phrases'] })
    },
  })
}

export function usePatchItem() {
  const qc = useQueryClient()
  const invalidate = useVocabInvalidate()
  return useMutation({
    mutationFn: (v: {
      itemId: string
      kind: ItemKind
      status: 'tracked' | 'known' | 'ignored'
      confidence: number | null
    }) => vocabularyApi.patchItem(v.kind, v.itemId, { status: v.status, confidence: v.confidence }),
    onSuccess: () => {
      invalidate()
      // Same rationale as useBulkAction: a patch can change a phrase's
      // status, and an open reader must not keep highlighting stale state.
      void qc.invalidateQueries({ queryKey: ['phrases'] })
    },
  })
}
