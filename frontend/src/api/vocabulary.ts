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

export interface ItemState {
  item_id: string
  status: string
  confidence: number | null
}

export const vocabularyApi = {
  lookup: (lang: string, text: string, target: string) => {
    const q = new URLSearchParams({ lang, text, target })
    return api<WordLookup>(`/api/vocabulary/lookup?${q.toString()}`)
  },
  createItem: (body: {
    kind: 'token'; language_code: string; text: string
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
}
