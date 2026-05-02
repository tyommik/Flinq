import { api } from './client'

export type UserRole = 'learner' | 'admin'

export interface MeResponse {
  id: string
  email: string
  role: UserRole
  display_name: string
  ui_language_code: string
  learning_languages: string[]
  last_learning_language_code: string | null
  needs_onboarding: boolean
  onboarded_at: string | null
}

export interface OnboardingPayload {
  ui_language: string
  learning_languages: string[]
  translation_language: string
}

export const meApi = {
  get: () => api<MeResponse>('/me'),
  onboarding: (payload: OnboardingPayload) =>
    api<{ ok: boolean; redirect: string }>('/me/onboarding', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  setLastLanguage: (language_code: string) =>
    api<{ ok: boolean }>('/me/last-language', {
      method: 'PATCH',
      body: JSON.stringify({ language_code }),
    }),
  delete: (password: string) =>
    api<{ ok: boolean }>('/me', {
      method: 'DELETE',
      body: JSON.stringify({ password }),
    }),
}
