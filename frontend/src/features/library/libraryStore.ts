import { create } from 'zustand'

type Tab = 'continue' | 'lessons'

interface LibraryState {
  tab: Tab
  search: string
  visibility: 'all' | 'mine' | 'shared'
  page: number
  setTab: (t: Tab) => void
  setSearch: (q: string) => void
  setVisibility: (v: LibraryState['visibility']) => void
  setPage: (n: number) => void
  reset: () => void
}

export const useLibraryStore = create<LibraryState>((set) => ({
  tab: 'continue',
  search: '',
  visibility: 'all',
  page: 1,
  setTab: (tab) => set({ tab, page: 1 }),
  setSearch: (search) => set({ search, page: 1 }),
  setVisibility: (visibility) => set({ visibility, page: 1 }),
  setPage: (page) => set({ page }),
  reset: () => set({ tab: 'continue', search: '', visibility: 'all', page: 1 }),
}))
