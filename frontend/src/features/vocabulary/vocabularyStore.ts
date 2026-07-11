import { create } from 'zustand'

export type VocabTab = 'all' | 'words' | 'phrases' | 'due'

interface VocabularyState {
  q: string
  statuses: ('tracked' | 'known' | 'ignored')[]
  confidence: [number, number] | null
  tags: string[]
  addedPreset: '7d' | '30d' | 'all'
  sort: 'created_at' | 'text'
  sortDir: 'asc' | 'desc'
  page: number
  pageSize: 25 | 50 | 100
  selection: string[]
  showAuto: boolean
  setQ: (q: string) => void
  setStatuses: (statuses: VocabularyState['statuses']) => void
  setConfidence: (confidence: VocabularyState['confidence']) => void
  setTags: (tags: string[]) => void
  setAddedPreset: (addedPreset: VocabularyState['addedPreset']) => void
  setSort: (sort: VocabularyState['sort'], sortDir: VocabularyState['sortDir']) => void
  setShowAuto: (showAuto: boolean) => void
  setPage: (page: number) => void
  setPageSize: (pageSize: VocabularyState['pageSize']) => void
  toggleSelected: (id: string) => void
  selectMany: (ids: string[]) => void
  clearSelection: () => void
  resetFilters: () => void
  filtersAreDefault: () => boolean
}

const DEFAULT_STATUSES: VocabularyState['statuses'] = ['tracked', 'known', 'ignored']

export const useVocabularyStore = create<VocabularyState>()((set, get) => ({
  q: '',
  statuses: DEFAULT_STATUSES,
  confidence: null,
  tags: [],
  addedPreset: 'all',
  sort: 'created_at',
  sortDir: 'desc',
  page: 1,
  pageSize: 25,
  selection: [],
  showAuto: false,
  setQ: (q) => set({ q, page: 1, selection: [] }),
  setStatuses: (statuses) => set({ statuses, page: 1, selection: [] }),
  setConfidence: (confidence) => set({ confidence, page: 1, selection: [] }),
  setTags: (tags) => set({ tags, page: 1, selection: [] }),
  setAddedPreset: (addedPreset) => set({ addedPreset, page: 1, selection: [] }),
  setSort: (sort, sortDir) => set({ sort, sortDir, page: 1, selection: [] }),
  setShowAuto: (showAuto) => set({ showAuto, page: 1, selection: [] }),
  setPage: (page) => set({ page }),
  setPageSize: (pageSize) => set({ pageSize, page: 1, selection: [] }),
  toggleSelected: (id) => set((s) => ({
    selection: s.selection.includes(id)
      ? s.selection.filter((x) => x !== id)
      : [...s.selection, id],
  })),
  selectMany: (ids) => set({ selection: ids }),
  clearSelection: () => set({ selection: [] }),
  resetFilters: () => set({
    q: '',
    statuses: DEFAULT_STATUSES,
    confidence: null,
    tags: [],
    addedPreset: 'all',
    page: 1,
    selection: [],
    showAuto: false,
  }),
  filtersAreDefault: () => {
    const s = get()
    return (
      s.q === '' &&
      s.statuses.length === DEFAULT_STATUSES.length &&
      DEFAULT_STATUSES.every((status) => s.statuses.includes(status)) &&
      s.confidence === null &&
      s.tags.length === 0 &&
      s.addedPreset === 'all' &&
      !s.showAuto
    )
  },
}))
