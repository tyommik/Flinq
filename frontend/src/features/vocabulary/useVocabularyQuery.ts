import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { vocabularyApi } from '@/api/vocabulary'
import type { VocabListParams } from '@/api/vocabulary'

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
  const invalidate = useVocabInvalidate()
  return useMutation({ mutationFn: vocabularyApi.bulk, onSuccess: invalidate })
}

export function usePatchItem() {
  const invalidate = useVocabInvalidate()
  return useMutation({
    mutationFn: (v: { itemId: string; status: 'tracked' | 'known' | 'ignored'; confidence: number | null }) =>
      vocabularyApi.patchItem('token', v.itemId, { status: v.status, confidence: v.confidence }),
    onSuccess: invalidate,
  })
}
