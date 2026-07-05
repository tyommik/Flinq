import { api } from './client'

export interface WordToken {
  t: string
  n: string
  i: number
}
export interface WhitespaceToken {
  ws: string
}
export interface PunctToken {
  p: string
}
export type Token = WordToken | WhitespaceToken | PunctToken
export const isWord = (tok: Token): tok is WordToken => 't' in tok

export interface Sentence {
  seg_id: string
  index: number
  text: string
  normalized_text: string
  tokens: Token[]
}
export interface Paragraph {
  sentences: Sentence[]
}
export interface LessonContent {
  lesson_id: string
  language_code: string
  word_count: number
  paragraphs: Paragraph[]
}

export type TokenStatus = 'tracked' | 'known' | 'ignored'
export interface TokenStatusEntry {
  s: TokenStatus
  c?: number | null
}
export type StatusMap = Record<string, TokenStatusEntry>

export interface ReaderPosition {
  view_mode: 'page' | 'sentence'
  current_segment_id: string | null
  current_token_ordinal: number | null
}
export interface BulkKnownResult {
  action_id: string
  created_count: number
}
export interface SegmentTranslation {
  text: string
  source: string
  model: string
  stored: boolean
}

export const readerApi = {
  content: (lessonId: string) => api<LessonContent>(`/api/lessons/${lessonId}/content`),
  statuses: (lessonId: string) =>
    api<{ statuses: StatusMap }>(`/api/lessons/${lessonId}/token-statuses`).then((r) => r.statuses),
  putPosition: (body: { lesson_id: string } & ReaderPosition) =>
    api<void>('/api/reader/positions', { method: 'PUT', body: JSON.stringify(body) }),
  bulkKnown: (body: { lesson_id: string; from_ordinal: number; to_ordinal: number }) =>
    api<BulkKnownResult>('/api/reader/bulk-known', { method: 'POST', body: JSON.stringify(body) }),
  undoBulk: (actionId: string) =>
    api<{ undone_count: number }>(`/api/reader/bulk-actions/${actionId}/undo`, { method: 'POST' }),
  segmentTranslation: (lessonId: string, segId: string, target: string) =>
    api<SegmentTranslation>(`/api/lessons/${lessonId}/segments/${segId}/translation`, {
      method: 'POST',
      body: JSON.stringify({ target_language_code: target }),
    }),
}
