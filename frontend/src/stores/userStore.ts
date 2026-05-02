import { create } from 'zustand'

import type { MeResponse } from '@/api/me'

interface UserState {
  user: MeResponse | null
  currentLang: string | null
  setUser: (user: MeResponse | null) => void
  setCurrentLang: (lang: string) => void
  reset: () => void
}

export const useUserStore = create<UserState>((set) => ({
  user: null,
  currentLang: null,
  setUser: (user) =>
    set({
      user,
      currentLang: user?.last_learning_language_code ?? user?.learning_languages[0] ?? null,
    }),
  setCurrentLang: (lang) => set({ currentLang: lang }),
  reset: () => set({ user: null, currentLang: null }),
}))
