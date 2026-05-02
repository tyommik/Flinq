import { api } from './client'

export interface RegisterPayload {
  display_name: string
  email: string
  password: string
}

export interface LoginPayload {
  email: string
  password: string
  remember_me: boolean
}

export interface AuthResponse {
  id: string
  needs_onboarding: boolean
}

export const authApi = {
  register: (payload: RegisterPayload) =>
    api<AuthResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  login: (payload: LoginPayload) =>
    api<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  logout: () => api<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
}
