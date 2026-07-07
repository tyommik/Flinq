import { api } from './client'

export interface TranslateResponse {
  hints: { text: string }[]
  model: string
  latency_ms: number
}

export const aiApi = {
  translate: (body: {
    surface_text: string; context_text: string
    target_language_code: string; lesson_id?: string
  }) => api<TranslateResponse>('/api/ai/translate', { method: 'POST', body: JSON.stringify(body) }),
}
