import { api } from './client'

export type LessonVisibility = 'private' | 'shared'
export type LessonStatus = 'draft' | 'processing' | 'ready' | 'failed' | 'archived'

export interface LessonSummary {
  id: string
  title: string
  language_code: string
  word_count: number
  visibility: LessonVisibility
  status: LessonStatus
  created_at: string
}

export interface LessonListResponse {
  items: LessonSummary[]
  total: number
  page: number
  page_size: number
}

export interface CreateLessonPayload {
  title: string
  language_code: string
  raw_text: string
  visibility?: LessonVisibility
}

interface ListParams {
  tab?: 'continue' | 'lessons'
  q?: string
  visibility?: 'mine' | 'shared' | 'all'
  page?: number
  page_size?: number
}

export const lessonsApi = {
  list: (lang: string, params: ListParams = {}) => {
    const search = new URLSearchParams({ lang, ...Object.fromEntries(
      Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])
    ) })
    return api<LessonListResponse>(`/api/lessons?${search.toString()}`)
  },
  create: (data: CreateLessonPayload) =>
    api<LessonSummary>('/api/lessons', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}
