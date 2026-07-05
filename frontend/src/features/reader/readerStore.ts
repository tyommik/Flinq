import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ViewMode = 'page' | 'sentence'

interface FontPrefs {
  size: 0 | 1 | 2
  lineHeight: 0 | 1 | 2
  serif: boolean
}

interface ReaderState {
  mode: ViewMode
  pageIndex: number
  sentenceFlatIndex: number
  sidebarOpen: boolean
  lastBulkActionId: string | null
  font: FontPrefs
  setMode: (m: ViewMode) => void
  setPageIndex: (i: number) => void
  setSentenceFlatIndex: (i: number) => void
  toggleSidebar: () => void
  setLastBulkActionId: (id: string | null) => void
  setFont: (f: Partial<FontPrefs>) => void
}

export const useReaderStore = create<ReaderState>()(
  persist(
    (set) => ({
      mode: 'page',
      pageIndex: 0,
      sentenceFlatIndex: 0,
      sidebarOpen: false,
      lastBulkActionId: null,
      font: { size: 1, lineHeight: 1, serif: false },
      setMode: (mode) => set({ mode }),
      setPageIndex: (pageIndex) => set({ pageIndex }),
      setSentenceFlatIndex: (sentenceFlatIndex) => set({ sentenceFlatIndex }),
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setLastBulkActionId: (lastBulkActionId) => set({ lastBulkActionId }),
      setFont: (f) => set((s) => ({ font: { ...s.font, ...f } })),
    }),
    { name: 'flinq-reader-prefs', partialize: (s) => ({ font: s.font }) as Partial<ReaderState> },
  ),
)
