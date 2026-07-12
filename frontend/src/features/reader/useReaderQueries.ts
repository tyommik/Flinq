import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { lessonsApi } from '@/api/lessons'
import { readerApi } from '@/api/reader'
import { vocabularyApi } from '@/api/vocabulary'

export function useLessonDetail(lessonId: string) {
  return useQuery({
    queryKey: ['lesson', lessonId],
    queryFn: () => lessonsApi.get(lessonId),
    refetchInterval: (query) => (query.state.data?.status === 'processing' ? 2000 : false),
  })
}

export function useLessonContent(lessonId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['reader-content', lessonId],
    queryFn: () => readerApi.content(lessonId),
    staleTime: Infinity,
    gcTime: Infinity,
    enabled,
  })
}

export function useTokenStatuses(lessonId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['reader-statuses', lessonId],
    queryFn: () => readerApi.statuses(lessonId),
    enabled,
  })
}

export function usePutPosition() {
  return useMutation({
    mutationFn: readerApi.putPosition,
  })
}

export function useBulkKnown(lessonId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: readerApi.bulkKnown,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['reader-statuses', lessonId] })
    },
  })
}

export function useUndoBulk(lessonId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: readerApi.undoBulk,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['reader-statuses', lessonId] })
    },
  })
}

export function usePhrases(lang: string, enabled: boolean) {
  return useQuery({
    queryKey: ['phrases', lang],
    queryFn: () => vocabularyApi.phrases(lang),
    enabled,
  })
}

export function useSegmentTranslation(
  lessonId: string,
  segId: string,
  target: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ['segment-translation', segId, target],
    queryFn: () => readerApi.segmentTranslation(lessonId, segId, target),
    staleTime: Infinity,
    enabled,
  })
}
