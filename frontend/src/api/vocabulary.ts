import { api } from './client'

export type ItemKind = 'token' | 'phrase'
export type CardStatus = 'new' | 'tracked' | 'known' | 'ignored'
export type WriteStatus = 'tracked' | 'known' | 'ignored'
export type SourceType = 'user' | 'ai' | 'dictionary'

export interface TranslationOut {
  id: string
  text: string
  target_language_code: string
  is_primary: boolean
  source_type: SourceType
}

export interface WordLookup {
  item_id: string | null
  status: CardStatus
  confidence: number | null
  translations: { primary: TranslationOut | null; all: TranslationOut[] }
  note: string | null
  tags: string[]
}

export interface PhraseListEntry {
  item_id: string
  phrase_text: string
  status: 'tracked' | 'known' | 'ignored'
  confidence: number | null
}

export interface ItemState {
  item_id: string
  status: string
  confidence: number | null
}

export interface VocabListItem {
  item_id: string
  kind: 'token' | 'phrase'
  text: string
  status: 'tracked' | 'known' | 'ignored'
  confidence: number | null
  primary_translation: { text: string; target_language_code: string } | null
  tags: string[]
  pos: string | null
  context: string | null
  created_at: string
}

export interface VocabListResponse {
  items: VocabListItem[]
  total: number
  page: number
  page_size: number
}

export interface VocabListParams {
  lang: string
  target?: string
  status?: ('tracked' | 'known' | 'ignored')[]
  confidence_min?: number
  confidence_max?: number
  tag?: string[]
  q?: string
  added_after?: string
  sort?: 'created_at' | 'text'
  sort_dir?: 'asc' | 'desc'
  page?: number
  page_size?: number
  kind?: 'token' | 'phrase' | 'all'
  added_by?: 'user' | 'all'
}

export const vocabularyApi = {
  lookup: (lang: string, text: string, target: string, kind: ItemKind = 'token') => {
    const q = new URLSearchParams({ lang, text, target, kind })
    return api<WordLookup>(`/api/vocabulary/lookup?${q.toString()}`)
  },
  phrases: (lang: string) => {
    const q = new URLSearchParams({ lang })
    return api<{ phrases: PhraseListEntry[] }>(`/api/vocabulary/phrases?${q.toString()}`).then(
      (r) => r.phrases,
    )
  },
  createItem: (body: {
    kind: ItemKind; language_code: string; text: string
    status: WriteStatus; confidence: number | null
  }) => api<ItemState>('/api/vocabulary/items', { method: 'POST', body: JSON.stringify(body) }),
  patchItem: (kind: ItemKind, id: string, body: { status: WriteStatus; confidence: number | null }) =>
    api<ItemState>(`/api/vocabulary/items/${kind}/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  addTranslation: (kind: ItemKind, id: string, body: {
    target_language_code: string; translation_text: string
    source_type?: SourceType
  }) => api<TranslationOut>(`/api/vocabulary/items/${kind}/${id}/translations`, {
    method: 'POST', body: JSON.stringify(body),
  }),
  updateTranslation: (kind: ItemKind, id: string, translationId: string, translation_text: string) =>
    api<TranslationOut>(`/api/vocabulary/items/${kind}/${id}/translations/${translationId}`, {
      method: 'PATCH', body: JSON.stringify({ translation_text }),
    }),
  deleteTranslation: (kind: ItemKind, id: string, translationId: string) =>
    api<{ translations: TranslationOut[] }>(
      `/api/vocabulary/items/${kind}/${id}/translations/${translationId}`,
      { method: 'DELETE' },
    ),
  putNote: (kind: ItemKind, id: string, note_text: string) =>
    api<{ note: string }>(`/api/vocabulary/items/${kind}/${id}/notes`, {
      method: 'PUT', body: JSON.stringify({ note_text }),
    }),
  addTag: (kind: ItemKind, id: string, tag_name: string) =>
    api<{ tags: string[] }>(`/api/vocabulary/items/${kind}/${id}/tags`, {
      method: 'POST', body: JSON.stringify({ tag_name }),
    }),
  removeTag: (kind: ItemKind, id: string, tag: string) =>
    api<{ tags: string[] }>(`/api/vocabulary/items/${kind}/${id}/tags/${encodeURIComponent(tag)}`, {
      method: 'DELETE',
    }),
  list: (p: VocabListParams) => {
    const qp = new URLSearchParams()
    qp.set('lang', p.lang)
    if (p.target) qp.set('target', p.target)
    for (const s of p.status ?? []) qp.append('status', s)
    if (p.confidence_min != null) qp.set('confidence_min', String(p.confidence_min))
    if (p.confidence_max != null) qp.set('confidence_max', String(p.confidence_max))
    for (const t of p.tag ?? []) qp.append('tag', t)
    if (p.q) qp.set('q', p.q)
    if (p.added_after) qp.set('added_after', p.added_after)
    if (p.sort) qp.set('sort', p.sort)
    if (p.sort_dir) qp.set('sort_dir', p.sort_dir)
    if (p.page) qp.set('page', String(p.page))
    if (p.page_size) qp.set('page_size', String(p.page_size))
    if (p.kind) qp.set('kind', p.kind)
    if (p.added_by) qp.set('added_by', p.added_by)
    return api<VocabListResponse>(`/api/vocabulary?${qp.toString()}`)
  },
  bulk: (body: {
    item_ids: string[]
    action: 'set_known' | 'set_ignored' | 'delete' | 'add_tag'
    tag_name?: string
  }) => api<{ affected: number }>('/api/vocabulary/bulk', {
    method: 'POST', body: JSON.stringify(body),
  }),
}
