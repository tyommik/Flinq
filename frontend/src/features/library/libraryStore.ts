import { create } from 'zustand'

interface LibraryState {
  search: string
  visibility: 'all' | 'mine' | 'shared'
  page: number
  setSearch: (q: string) => void
  setVisibility: (v: LibraryState['visibility']) => void
  setPage: (n: number) => void
  reset: () => void
}

export const useLibraryStore = create<LibraryState>((set) => ({
  search: '',
  visibility: 'all',
  page: 1,
  setSearch: (search) => set({ search, page: 1 }),
  setVisibility: (visibility) => set({ visibility, page: 1 }),
  setPage: (page) => set({ page }),
  reset: () => set({ search: '', visibility: 'all', page: 1 }),
}))
